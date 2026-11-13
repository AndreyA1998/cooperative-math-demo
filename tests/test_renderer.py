"""Real browser display regressions without loading the Python runtime."""
import json
import tempfile
import unittest

from support import HAS_BROWSER, prepare_browser, run_browser, static_origin


@unittest.skipUnless(HAS_BROWSER, "Requires Playwright with Chromium, or native macOS WebKit and Clang")
class RendererBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="math-demo-renderer-")
        cls.addClassCleanup(temporary.cleanup)
        cls.runner = prepare_browser(temporary.name)

    def render_case(self, script, page="__renderer_test__.html"):
        with static_origin() as server:
            result = run_browser(self.runner, server.url + page, script, timeout=45)
            self.assertIn("OK", result)
            self.assertFalse(any(path.endswith("worker.js") for _, path in server.requests))
            self.assertFalse(any(method == "POST" for method, _ in server.requests))

    def test_idle_interface_hides_runtime_status_and_has_no_technical_panels(self):
        self.render_case(r'''
          check(!document.querySelector(".technical-details, .page-footer"), "Technical panels or footer remain in the task interface");
          class FixtureWorker {
            constructor() { window.fixtureWorker = this; queueMicrotask(() => this.onmessage?.({data: {type: "ready"}})); }
            terminate() {}
            postMessage(message) {
              const payload = message.path === "/api/catalogue"
                ? {problems: [{id: "prealgebra/test/11", subject: "prealgebra", split: "test"}]}
                : {presentation: {inputs: [], segments: [{kind: "text", text: "Pattern"}], notes: []}};
              queueMicrotask(() => this.onmessage({data: {id: message.id, status: 200, raw: JSON.stringify(payload)}}));
            }
          }
          window.Worker = FixtureWorker;
          await import("./main.js");
          await until(idleAtomic, "ready controls");
          check(document.querySelector(".runtime-banner").hidden && !$("runtime-status").textContent, "Successful runtime leaves a permanent banner");
          window.fixtureWorker.onmessage({data: {type: "fatal", message: "Test failure"}});
          check(!document.querySelector(".runtime-banner").hidden && !$("runtime-retry").hidden, "Failure is hidden with the successful status");
          $("runtime-retry").click();
          check(!document.querySelector(".runtime-banner").hidden, "Retry loading state is hidden");
          await until(() => document.querySelector(".runtime-banner").hidden, "ready after retry");
          check(!$("runtime-status").textContent, "Retry kept an idle message");
          check($("atomic-copy").getAttribute("aria-label"), "Copy icon is not accessible");
          return "OK: quiet successful interface with visible real loading and failure states";
        ''', page="__component_test__.html")

    def test_missing_renderer_keeps_readable_math_colored_roles_and_literal_html(self):
        self.render_case(r'''
          window.katex = {render: () => { throw new Error("Renderer unavailable"); }};
          const {MathPresentation} = await import("./math-renderer.js");
          const target = document.createElement("div");
          document.body.append(target);
          const segments = [
            {kind: "text", text: "Find $x+"},
            {kind: "parameter", text: "R1.a", key: "R1.a", name: "a", role: "external", filled: false},
            {kind: "text", text: "$ and "},
            {kind: "parameter", text: "R2.b", key: "R2.b", name: "b", role: "internal", filled: false},
            {kind: "text", text: ". Literal <img src=x onerror=alert(1)> remains text."},
          ];
          check(await MathPresentation.render(target, segments) === false, "Failed renderer reported success");
          check(target.textContent === segments.map(value => value.text).join(""), "Fallback changed the exact statement");
          check(!target.querySelector("img"), "Native source text was interpreted as HTML");
          check(target.querySelector('[data-parameter="R1.a"].slot-external'), "Fallback lost the external parameter role");
          check(target.querySelector('[data-parameter="R2.b"].slot-internal'), "Fallback lost the internal parameter role");
          check(target.querySelector('.math-fragment[data-rendered="false"]'), "No readable failed formula fallback");
          return "OK: renderer failure keeps exact readable text and safe annotations";
        ''')

    def test_real_katex_preserves_structural_native_formulas_and_parameter_boxes(self):
        self.render_case(r'''
          const {MathPresentation} = await import("./math-renderer.js");
          const holder = document.createElement("div");
          document.body.append(holder);
          const slot = text => ({kind: "parameter", text, name: "fragment", key: "R1.fragment",
            role: "external", filled: true, parameters: ["a"]});
          const text = text => ({kind: "text", text});
          const formulas = [
            [text("$"), slot("\\frac{37"), slot("}{9}"), text("$")],
            [text("$x^{"), slot("12}+64^{12"), text("}$")],
            [text("Term one is $-\\frac{28}{"), slot("5}$ and term 32 is $-\\frac{766}{35"), text("}$")],
          ];
          for (const segments of formulas) {
            check(await MathPresentation.render(holder, segments), "Structural annotation broke native TeX");
            check(holder.querySelector(".katex"), "Native formula was not typeset");
            check(!holder.querySelector('.katex-error, [data-rendered="false"]'), "Valid native formula fell back to raw text");
          }
          const segments = [text("$\\frac{x^2+"),
            {kind: "parameter", text: "R1.a", key: "R1.a", role: "external", filled: false}, text("}{2}$")];
          check(await MathPresentation.render(holder, segments), "Named mathematical slot did not render");
          check(holder.querySelector(".katex .mfrac") && holder.querySelector(".katex .fbox"), "Parameter lost its formula or box");
          check(holder.textContent.includes("R1.a"), "Placeholder lost its stable name");
          segments[1] = {...segments[1], text: "5", filled: true};
          check(await MathPresentation.render(holder, segments), "Filled mathematical slot did not render");
          check(holder.querySelector(".katex .mfrac") && !holder.querySelector(".katex-error"), "Filled slot changed native TeX");
          return "OK: real KaTeX preserves structural math and boxed input slots";
        ''')


    def test_automatic_reuse_warning_preserves_preference_and_clears_on_exact_build(self):
        # This checks UI policy with a controlled worker response. Mathematical
        # generation and WASM transport are independently exercised in test_browser.
        from support import ensure_runtime
        ensure_runtime()
        from composite_dataset import build_schema, instantiate
        from math_demo.presentation import presentation
        schema = build_schema(2, 3, 42)
        fixture = {"schema": schema, "template": presentation(schema),
                   "instance": instantiate(schema, 7), "filled": presentation(schema, 7)}
        self.render_case("const fixture = " + json.dumps(fixture) + r''';
          class FixtureWorker {
            constructor() { queueMicrotask(() => this.onmessage?.({data: {type: "ready"}})); }
            terminate() {}
            postMessage(message) {
              const fields = message.body ? JSON.parse(message.body) : {};
              let payload;
              if (message.path === "/api/catalogue") {
                payload = {problems: [{id: "prealgebra/test/11", split: "test", subject: "prealgebra"}]};
              } else if (message.path === "/api/template") {
                payload = {presentation: {inputs: [], segments: [{kind: "text", text: "Pattern"}], notes: []}};
              } else if (message.path === "/api/composite/build") {
                payload = {...fixture.schema, seed: fields.seed, requested_width: fields.width,
                  requested_allow_template_reuse: fields.allow_template_reuse,
                  allow_template_reuse: fields.allow_template_reuse || fields.width === 300};
              } else if (message.path === "/api/composite/presentation") {
                payload = fixture.template;
              } else if (message.path === "/api/composite/variant") {
                payload = {instance: {...fixture.instance, parameter_seed: fields.seed}, presentation: fixture.filled};
              } else throw new Error("Unexpected fixture request: " + message.path);
              queueMicrotask(() => this.onmessage({data: {id: message.id, status: 200, raw: JSON.stringify(payload)}}));
            }
          }
          window.Worker = FixtureWorker;
          await import("./main.js");
          await until(idleAtomic, "controlled catalogue");
          $("composite-tab").click(); await until(idleComposite, "composite activation");
          const reuse = $("composite-reuse");
          const notice = $("composite-reuse-notice");
          const build = async width => {
            $("composite-width").value = width;
            $("composite-structure-random").click();
            await until(() => idleComposite() && !$("composite-schema-results").hidden, "controlled schema");
          };
          await build("300");
          check(!notice.hidden && notice.textContent.includes("повтор"), "Automatic reuse has no warning");
          check(!$("composite-width-notice").hidden, "Reuse warning displaced width warning");
          check(!reuse.checked, "Automatic reuse changed the user's preference");
          $("composite-parameter-random").click();
          await until(() => idleComposite() && !$("composite-instance-result").hidden, "controlled variant");
          check(!notice.hidden, "Generating a variant removed the schema's reuse warning");
          await build("3");
          check(notice.hidden && !reuse.checked, "Exact build kept a stale reuse warning");
          reuse.click();
          await build("300");
          check(notice.hidden && reuse.checked, "Explicit reuse was misreported as an automatic fallback");
          return "OK: automatic reuse warning preserves the user's preference";
        ''', page="__component_test__.html")


    def test_explicit_symbolic_math_renders_a_real_bare_recipe_with_boundary_guards(self):
        self.render_case(r'''
          const {MathPresentation} = await import("./math-renderer.js");
          const target = document.createElement("div"); document.body.append(target);
          const field = {kind: "parameter", text: "factorial sum(count)", name: "factorial sum", key: "sum", role: "external", filled: false,
            symbolic_math: "\\sum_{k=1}^{\\text{count}} k!"};
          const wrap = part => [{kind: "text", text: "Compute $"}, part, {kind: "text", text: "$."}];
          check(await MathPresentation.render(target, wrap(field)), "Symbolic recipe did not typeset");
          check(target.querySelector(".katex-html .mop"), "Bare sum is a text alias instead of mathematical notation");
          check(!target.textContent.includes("factorial sum("), "An opaque alias replaced the bare mathematical recipe");
          check(target.querySelector("annotation").textContent.includes("\\sum"), "Symbolic TeX was escaped as a label");
          await MathPresentation.render(target, wrap({...field, text: "\\frac{1}{2}", symbolic_math: undefined}));
          check(!target.querySelector(".mfrac"), "An ordinary label was promoted to executable math syntax");
          await MathPresentation.render(target, wrap({...field, text: "count", symbolic_math: "$ hidden $"}));
          check(!target.textContent.includes("hidden") && target.querySelectorAll(".math-fragment").length === 1,
                "Symbolic metadata crossed a math delimiter boundary");
          await MathPresentation.render(target, wrap({...field, text: "7", filled: true}));
          check(!target.querySelector("annotation").textContent.includes("\\sum"), "Filled value was replaced by a stale symbolic recipe");
          return "OK: real symbolic math with explicit metadata and safe boundaries";
        ''')


if __name__ == "__main__":
    unittest.main()
