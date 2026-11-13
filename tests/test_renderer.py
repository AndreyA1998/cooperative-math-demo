"""Real browser display regressions without loading the Python runtime."""
import json
import tempfile
import unittest

from support import HAS_WEBKIT, compile_webkit, run_webkit, static_origin


@unittest.skipUnless(HAS_WEBKIT, "Requires macOS system WebKit and Clang")
class RendererBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="math-demo-renderer-")
        cls.addClassCleanup(temporary.cleanup)
        cls.runner = compile_webkit(temporary.name)

    def render_case(self, script, page="__renderer_test__.html"):
        with static_origin() as server:
            result = run_webkit(self.runner, server.url + page, script, timeout=45)
            self.assertIn("OK", result)
            self.assertFalse(any(path.endswith("worker.js") for _, path in server.requests))
            self.assertFalse(any(method == "POST" for method, _ in server.requests))

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
        from mathgen.composite import build_schema, instantiate
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
          $("composite-tab").click();
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


if __name__ == "__main__":
    unittest.main()
