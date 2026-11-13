"""Actual browser + Pyodide integration against a static repository subpath."""
from copy import deepcopy
from hashlib import sha256
import json
import tempfile
import unittest

from support import (
    HAS_BROWSER, MOUNT, prepare_browser, ensure_runtime, run_browser, static_origin,
)

ensure_runtime()

from math_demo.api import dispatch_json
from composite_dataset import build_schema
from composite_dataset.profiles import get_catalogue
from template_dataset.registry import registry

MAX_SEED = "18446744073709551615"


def native(method, path, query="", body=None):
    status, raw = dispatch_json(method, path, query, body)
    if status != 200:
        raise AssertionError(raw)
    return raw


@unittest.skipUnless(HAS_BROWSER, "Requires Playwright with Chromium, or native macOS WebKit and Clang")
class BrowserRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="math-demo-webkit-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.runner = prepare_browser(cls.temporary.name)

    def run_case(self, script, *, suffix="", fail_once=(), timeout=240):
        with static_origin(fail_once=fail_once) as server:
            output = run_browser(self.runner, server.url + suffix, script, timeout=timeout)
            self.assertIn("OK", output)
            self.assertTrue(any(path.endswith("/worker.js") for _, path in server.requests))
            self.assertTrue(any(path.endswith("/runtime.zip") for _, path in server.requests))
            self.assertFalse(any(method == "POST" or "/api/" in path for method, path in server.requests),
                             "The browser tried to use an HTTP generator backend")

    def test_actual_wasm_matches_native_and_preserves_raw_large_schema_integers(self):
        structure = {"depth": 3, "width": 4, "seed": "42", "split": "train",
                     "allow_template_reuse": False}
        body = json.dumps(structure)
        expected_build = native("POST", "/api/composite/build", body=body)
        schema = json.loads(expected_build)
        chosen = {node["source_id"] for node in schema["nodes"]}
        catalogue = {key: deepcopy(get_catalogue()[key]) for key in chosen}
        for profiles in catalogue.values():
            for profile in profiles:
                for name in ("numerator", "denominator", "divisor"):
                    profile["classifier"][name] *= 2**100 + 1
        large = build_schema(3, 4, 42, catalogue=catalogue)
        raw_large = json.dumps(large, ensure_ascii=False, separators=(",", ":"))
        large_body = '{"schema":' + raw_large + ',"seed":"' + MAX_SEED + '"}'
        ids = sorted(registry())
        exact_outputs = sha256()
        for source_id in ids:
            raw = native("GET", "/api/generate", "id=" + source_id + "&seed=0")
            exact_outputs.update((raw + "\n").encode("utf-8"))
        fixtures = {
            "ids": ids, "atomicCatalogueDigest": exact_outputs.hexdigest(),
            "query": "id=prealgebra%2Ftest%2F11&seed=" + MAX_SEED,
            "atomic": native("GET", "/api/generate", "id=prealgebra%2Ftest%2F11&seed=" + MAX_SEED),
            "buildBody": body, "build": expected_build,
            "largeSchema": raw_large, "largeBody": large_body,
            "variant": native("POST", "/api/composite/variant", body=large_body),
        }
        self.run_case("const fixtures = " + json.dumps(fixtures) + r''';
          const {request} = await import("./transport.js");
          const atomic = await request("GET", "/api/generate", fixtures.query);
          check(atomic.raw === fixtures.atomic, "WASM atomic output differs from native Python");
          check(atomic.data.seed === "18446744073709551615", "Seed became a JS number");
          const schema = await request("POST", "/api/composite/build", "", fixtures.buildBody);
          check(schema.raw === fixtures.build, "WASM schema or catalogue fingerprint differs from native");
          const variant = await request("POST", "/api/composite/variant", "", fixtures.largeBody);
          check(variant.raw === fixtures.variant, "WASM variant/trace/presentation differs from native");
          check(variant.data.instance.parameter_seed === "18446744073709551615", "Parameter seed lost precision");
          let rejected = false;
          const rounded = JSON.stringify({schema: JSON.parse(fixtures.largeSchema), seed: "7"});
          try { await request("POST", "/api/composite/variant", "", rounded); }
          catch (error) { rejected = true; }
          check(rejected, "A JS-rounded large schema was silently accepted");
          const replay = await request("GET", "/api/generate", fixtures.query);
          check(replay.raw === atomic.raw, "A rejected request left the worker unusable");
          const rows = [];
          for (const sourceId of fixtures.ids) {
            const result = await request("GET", "/api/generate", "id=" + encodeURIComponent(sourceId) + "&seed=0");
            rows.push(result.raw + "\n");
          }
          const buffer = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(rows.join("")));
          const digest = [...new Uint8Array(buffer)].map(value => value.toString(16).padStart(2, "0")).join("");
          check(digest === fixtures.atomicCatalogueDigest,
                "Full atomic catalogue differs between native Python and WASM: " + digest);
          return "OK: actual WASM matches native for " + fixtures.ids.length + " atomic IDs and exact raw composite JSON";
        ''', timeout=900)

    def test_atomic_controls_replay_exact_seed_and_tabs_preserve_state(self):
        self.run_case(r'''
          await until(() => idleAtomic() && !$("atomic-problem-text").hidden, "shared atomic link");
          check($("atomic-seed-mode").checked && !$("atomic-seed-setting").hidden, "Share link lost seed mode");
          check($("atomic-seed").value === "0", "Share link lost exact seed");
          check($("atomic-problem-id").value === "algebra/train/1316", "Share link lost selection");
          check($("atomic-params").textContent.includes("99999999999999999999999999999999999999"),
                "Large native parameter lost decimal digits");
          check(!$("atomic-answer").hidden && $("atomic-answer").tagName !== "DETAILS",
                "Atomic answer is not immediately visible");
          const previous = $("atomic-problem-text").textContent;
          $("composite-tab").click();
          check($("atomic-panel").hidden && !$("composite-panel").hidden, "Composite tab did not activate");
          check(location.hash === "#composite", "Composite tab has no addressable state");
          $("atomic-tab").click();
          check($("atomic-problem-text").textContent === previous, "Tab switch discarded the atomic task");
          check(new URL(location.href).searchParams.get("seed") === "0", "Tab switch discarded replay parameters");
          change("atomic-subject", "prealgebra");
          await until(idleAtomic, "subject pattern");
          change("atomic-split", "test");
          await until(idleAtomic, "split pattern");
          change("atomic-problem-id", "prealgebra/test/11");
          await until(idleAtomic, "selected pattern");
          if (!$("atomic-seed-mode").checked) $("atomic-seed-mode").click();
          const options = [...$("atomic-problem-id").options];
          check(options.every((option, index) => option.value.startsWith("prealgebra/test/")
            && /^\d+$/.test(option.text)
            && (index === 0 || Number(options[index - 1].text) < Number(option.text))),
            "Task selector is not filtered and numerically ordered");
          $("atomic-seed").value = "18446744073709551615";
          $("atomic-generate").click();
          await until(idleAtomic, "exact atomic replay");
          check($("atomic-seed").value === "18446744073709551615", "Full uint64 seed changed");
          check($("atomic-answer-value").textContent === "3/4", "Exact atomic answer differs from 3/4");
          const fixed = $("atomic-problem-text").textContent;
          $("atomic-generate").click();
          await until(idleAtomic, "second atomic replay");
          check($("atomic-problem-text").textContent === fixed, "Atomic replay changed the question");
          Math.random = () => 0;
          $("atomic-generate-random").click();
          await until(idleAtomic, "random filtered task");
          check($("atomic-problem-id").value === options[0].value, "Random task ignored active filters");
          check(!$("atomic-seed-mode").checked && $("atomic-seed-setting").hidden, "Random task kept replay mode");
          check($("atomic-answer-value").textContent === "—" && !$("atomic-params").querySelector(".slot-filled"), "Random selection filled numbers before the separate action");
          return "OK: atomic controls, exact seed, visible answer and persistent tabs";
        ''', suffix="?id=algebra%2Ftrain%2F1316&seed=0#atomic")

    def test_composite_generation_presentation_export_reset_and_width_fallback(self):
        fields = {"depth": 3, "width": 4, "seed": "42", "split": "train", "allow_template_reuse": False}
        raw_schema = native("POST", "/api/composite/build", body=json.dumps(fields))
        schema = json.loads(raw_schema)
        raw_variant = native("POST", "/api/composite/variant", body='{"schema":' + raw_schema + ',"seed":"' + MAX_SEED + '"}')
        variant = json.loads(raw_variant)
        expected = {"schemaRaw": raw_schema, "variantRaw": raw_variant, "modelTemplate": schema["problem_template"],
                    "modelInstance": variant["instance"]["problem"], "answer": variant["instance"]["answer"],
                    "nodes": len(schema["nodes"]), "origins": [{"node_id": node["node_id"], "number": node["number"], "source_id": node["source_id"]} for node in schema["nodes"]]}
        self.run_case("const expected = " + json.dumps(expected) + r''';
          await until(idleAtomic, "runtime ready");
          check(!$("composite-panel").hidden && $("atomic-panel").hidden, "Direct composite tab link failed");
          let copied, exported;
          Object.defineProperty(navigator, "clipboard", {configurable: true,
            value: {writeText: async text => { copied = text; }}});
          const objectURL = URL.createObjectURL;
          URL.createObjectURL = blob => { exported = blob; return objectURL(blob); };
          const anchorClick = HTMLAnchorElement.prototype.click;
          HTMLAnchorElement.prototype.click = function() { if (!this.download) anchorClick.call(this); };
          const reset = $("composite-reset-parameters");
          check(reset.disabled, "Reset enabled without a variant");
          $("composite-structure-seed-mode").click();
          $("composite-structure-seed").value = "42";
          $("composite-structure-random").click();
          await until(() => idleComposite() && !$("composite-schema-results").hidden, "real schema build");
          const template = $("composite-public-template");
          check(template.querySelectorAll(".subproblem-card").length === expected.nodes, "Missing rendered subproblems");
          check(template.querySelector(".slot-external"), "Missing external placeholders");
          check(template.querySelector('.slot-internal, .math-fragment[title*="Внутренний вход"]'),
                "Missing internal placeholders");
          check($("composite-tree").matches("svg")
            && $("composite-tree").querySelectorAll(".tree-node").length === expected.nodes,
                "Hierarchy diagram omitted mathematical nodes");
          const subjectNames = {algebra:"Алгебра", counting_and_probability:"Комбинаторика и вероятность", geometry:"Геометрия", intermediate_algebra:"Продвинутая алгебра", number_theory:"Теория чисел", prealgebra:"Начальная алгебра", precalculus:"Предварительный курс анализа"};
          for (const item of expected.origins) {
            const group = $("composite-tree").querySelector('[data-node="' + item.node_id + '"]');
            const [subject, split, number] = item.source_id.split("/");
            check(group.querySelector(".tree-label").textContent === String(item.number), "Provenance replaced the local task number");
            check(group.textContent.includes(subjectNames[subject]) && group.textContent.includes("№ " + number + " · " + split), "Tree vertex lacks readable source provenance");
            check(!group.textContent.includes(item.source_id), "Tree exposes slash-delimited technical IDs");
          }
          check(!document.querySelector("details, .canvas-footer, .page-footer"), "Unwanted expanders or legends remain");
          check(template.querySelector(".conversion-rule"), "Removing expanders hid the required conversion rules");
          $("composite-copy-current").click();
          await until(() => copied !== undefined, "copy model template");
          check(copied === expected.modelTemplate, "Copy changed the model-facing schema text");
          $("composite-export-schema").click();
          check(exported && await exported.text() === expected.schemaRaw, "Export reserialized or changed raw schema JSON");
          await until(() => !$("composite-presentation-note").hidden
            || [...template.querySelectorAll(".math-fragment")].every(node => node.hasAttribute("data-rendered")),
            "template typesetting", {timeout: 20000});
          const templateBefore = template.textContent;
          const treeBefore = $("composite-tree").innerHTML;
          $("composite-parameter-seed-mode").click();
          $("composite-parameter-seed").value = "18446744073709551615";
          $("composite-parameter-random").click();
          await until(() => idleComposite() && !$("composite-instance-result").hidden, "real parameter variant");
          check($("composite-root-answer").textContent === expected.answer, "Wrong exact root answer");
          check(template.querySelector(".slot-filled"), "Bottom values were not filled");
          copied = undefined;
          $("composite-copy-current").click();
          await until(() => copied !== undefined, "copy model instance");
          check(copied === expected.modelInstance, "Copy changed the model-facing instance");
          $("composite-export-schema").click();
          check(await exported.text() === '{"schema":' + expected.schemaRaw + ',"variant":' + expected.variantRaw + '}', "Ready task download lost exact original schema or instance payload");
          check($("composite-export-schema").textContent === "Скачать задачу", "Ready task has no visible download action");
          check(!reset.disabled, "Reset unavailable after generation");
          $("atomic-tab").click();
          $("composite-tab").click();
          check(!$("composite-instance-result").hidden, "Tab switch discarded a composite variant");
          check($("composite-root-answer").getBoundingClientRect().height > 0, "Answer is not visible");
          reset.click();
          check($("composite-instance-result").hidden, "Reset kept a stale variant");
          check(!$("composite-root-answer").textContent && !template.querySelector(".subproblem-answer, .slot-filled"), "Reset retained answer or values");
          await until(() => [...template.querySelectorAll(".math-fragment")].every(node => node.hasAttribute("data-rendered")) || !$("composite-presentation-note").hidden, "reset typesetting", {timeout: 20000});
          check(template.textContent === templateBefore && $("composite-tree").innerHTML === treeBefore,
                "Reset changed the schema or placeholders");
          check(reset.disabled && !$("composite-parameter-controls").disabled, "Cannot regenerate after reset");
          $("composite-parameter-random").click();
          await until(() => idleComposite() && !$("composite-instance-result").hidden, "replay after reset");
          check($("composite-root-answer").textContent === expected.answer, "Reset broke seed replay");
          const {MathPresentation} = await import("./math-renderer.js");
          const originalRender = MathPresentation.render;
          const pending = [];
          MathPresentation.render = (...args) => {
            void originalRender(...args);
            return new Promise(resolve => pending.push(resolve));
          };
          reset.click();
          $("composite-parameter-random").click();
          await until(() => idleComposite() && !$("composite-instance-result").hidden, "variant with delayed rendering");
          check(pending.length > 0, "No pending renderer result to test");
          reset.click();
          pending.splice(0).forEach(resolve => resolve(false));
          await new Promise(resolve => setTimeout(resolve, 50));
          check($("composite-instance-result").hidden && !template.querySelector(".subproblem-answer, .slot-filled"), "Late rendering restored discarded state after reset");
          MathPresentation.render = originalRender;
          $("composite-depth").value = "1";
          $("composite-width").value = "300";
          check($("composite-width").checkValidity(), "Wide requested width blocked by form validation");
          $("composite-structure-random").click();
          await until(idleComposite, "width fallback");
          const notice = $("composite-width-notice");
          check(!notice.hidden && /\b300\b/.test(notice.textContent) && /\b1\b/.test(notice.textContent)
            && /\b128\b/.test(notice.textContent), "Reduced width notice omits requested, actual or technical limit");
          check(!$("composite-parameter-controls").disabled, "Reduced schema cannot generate variants");
          $("composite-width").value = "1";
          $("composite-structure-random").click();
          await until(idleComposite, "exact width rebuild");
          check(notice.hidden, "An exact build kept the old width warning");
          return "OK: composite presentation, exact export, reset and width fallback";
        ''', suffix="#composite")

    def test_runtime_download_failure_is_visible_and_retry_restores_generation(self):
        self.run_case(r'''
          await until(() => !$("runtime-retry").hidden, "visible runtime failure", {allowError: true});
          check($("runtime-status").classList.contains("error"), "Failed download has no error state");
          check($("runtime-status").textContent.includes("Повтор") || $("runtime-status").textContent.includes("повтор"),
                "Failure provides no retry guidance");
          $("runtime-retry").click();
          await until(() => idleAtomic() || !$("runtime-retry").hidden, "runtime retry", {allowError: true});
          check($("runtime-retry").hidden, "Retry failed: " + $("runtime-status").textContent);
          const {request} = await import("./transport.js");
          const result = await request("GET", "/api/generate", "id=prealgebra%2Ftest%2F11&seed=18446744073709551615");
          check(result.data.answer === "3/4", "Recovered runtime cannot generate exact answers");
          return "OK: failed static download recovered through the retry button";
        ''', fail_once=(MOUNT + "runtime.zip",))


if __name__ == "__main__":
    unittest.main()
