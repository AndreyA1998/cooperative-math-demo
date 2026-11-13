"""Mobile-width layout with actual browser, Pyodide and filled mathematics."""
import tempfile
import unittest

from support import HAS_BROWSER, MOUNT, prepare_browser, run_browser, static_origin


@unittest.skipUnless(HAS_BROWSER, "Requires Playwright with Chromium, or native macOS WebKit and Clang")
class MobileLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="math-demo-mobile-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.runner = prepare_browser(cls.temporary.name)

    def test_390px_real_variants_keep_controls_and_math_inside_the_page(self):
        # The existing runner is 1280px wide. A same-origin iframe gives CSS
        # and window.innerWidth a real 390px viewport without changing support.
        script = r'''
          document.body.style.margin = "0";
          const frame = document.createElement("iframe");
          frame.title = "Mobile viewport";
          frame.style.cssText = "display:block;width:390px;height:844px;border:0;max-width:none";
          frame.src = "./#atomic";
          const loaded = new Promise(resolve => frame.addEventListener("load", resolve, {once: true}));
          document.body.append(frame);
          await loaded;
          const mobile = frame.contentWindow;
          const page = frame.contentDocument;
          const at = id => page.getElementById(id);
          const waitFor = (condition, label, timeout = 150000) => until(() => {
            const error = [...page.querySelectorAll(".status.error:not([hidden]), #runtime-status.error")]
              .find(element => element.textContent);
            if (error) throw new Error(label + ": " + error.textContent);
            return condition();
          }, label, {timeout});
          const atomicIdle = () => !at("atomic-catalogue-controls").disabled && at("atomic-status").hidden;
          const compositeIdle = () => !at("composite-structure-controls").disabled && at("composite-status").hidden;
          const changeField = (id, value) => {
            at(id).value = value;
            at(id).dispatchEvent(new mobile.Event("change", {bubbles: true}));
          };
          const inside = id => {
            const node = at(id);
            node.scrollIntoView({block: "center", inline: "nearest"});
            const rectangle = node.getBoundingClientRect();
            check(rectangle.width > 0 && rectangle.height > 0, id + " is not visible");
            check(rectangle.left >= -1 && rectangle.right <= mobile.innerWidth + 1,
                  id + " is outside the mobile viewport: " + rectangle.left + ".." + rectangle.right);
          };
          const noOverflow = label => {
            const width = Math.max(page.documentElement.scrollWidth, page.body.scrollWidth);
            check(mobile.innerWidth === 390, "Iframe did not create a true mobile viewport");
            check(width <= 391, label + " makes the document " + width + "px wide at 390px");
          };
          const settledMath = async (targetId, noteId) => {
            await waitFor(() => !at(noteId).hidden || [...at(targetId).querySelectorAll(".math-fragment")]
              .every(node => node.hasAttribute("data-rendered")), "math layout", 20000);
            await page.fonts.ready;
            // Geometry reads below force layout; offscreen WebKit suspends rAF.
          };

          await waitFor(atomicIdle, "mobile WASM catalogue");
          inside("atomic-tab");
          inside("composite-tab");
          inside("atomic-subject");
          inside("atomic-problem-id");
          mobile.Math.random = () => 0;
          at("atomic-generate-random").click();
          await waitFor(() => atomicIdle() && !at("atomic-problem-text").hidden, "mobile random task");
          check(!at("atomic-answer").hidden && at("atomic-answer-value").textContent === "—",
                "Random task should show a bare pattern with an answer placeholder");
          at("atomic-generate").click();
          await waitFor(atomicIdle, "mobile filled random task");
          check(at("atomic-answer-value").textContent !== "—", "Filled atomic answer is not visible");
          noOverflow("random atomic task");

          // A native problem with a long, exact integer inside a TeX formula.
          changeField("atomic-subject", "algebra");
          await waitFor(atomicIdle, "subject pattern");
          changeField("atomic-split", "train");
          await waitFor(atomicIdle, "split pattern");
          changeField("atomic-problem-id", "algebra/train/1316");
          await waitFor(atomicIdle, "selected pattern");
          at("atomic-seed-mode").click();
          check(!at("atomic-seed-setting").hidden && !at("atomic-seed").disabled,
                "Mobile atomic seed checkbox does not expose a usable input");
          inside("atomic-seed");
          at("atomic-seed").value = "0";
          at("atomic-generate").click();
          await waitFor(atomicIdle, "mobile exact long formula");
          await settledMath("atomic-problem-text", "atomic-renderer-note");
          const formula = at("atomic-problem-text").querySelector(".math-fragment");
          check(formula && formula.textContent.includes("99,999,999,999"), "Native long formula is missing");
          check(formula.clientWidth > 0 && formula.getBoundingClientRect().width <= 390,
                "Long formula is not constrained to its readable container");
          check(mobile.getComputedStyle(formula).overflowX === "auto", "Long formula has no internal scrolling");
          noOverflow("filled long atomic formula");
          const atomicAnswer = at("atomic-answer-value").textContent;

          at("composite-tab").click();
          check(mobile.location.hash === "#composite" && !at("composite-panel").hidden,
                "Mobile tab does not activate the composite panel");
          inside("composite-depth");
          inside("composite-width");
          inside("composite-structure-random");
          at("composite-structure-seed-mode").click();
          check(!at("composite-structure-seed-setting").hidden && !at("composite-structure-seed").disabled,
                "Mobile structure seed input is unusable");
          inside("composite-structure-seed");
          at("composite-structure-seed").value = "42";
          at("composite-depth").value = "3";
          at("composite-width").value = "4";
          at("composite-structure-random").click();
          await waitFor(() => compositeIdle() && !at("composite-schema-results").hidden, "mobile real schema");
          await settledMath("composite-public-template", "composite-presentation-note");
          const tree = at("composite-tree-viewport");
          check(tree.scrollWidth > tree.clientWidth && mobile.getComputedStyle(tree).overflowX === "auto",
                "Wide tree does not scroll within its own viewport");
          noOverflow("composite schema and tree");
          inside("composite-parameter-random");
          at("composite-parameter-seed-mode").click();
          check(!at("composite-parameter-seed-setting").hidden && !at("composite-parameter-seed").disabled,
                "Mobile parameter seed input is unusable");
          inside("composite-parameter-seed");
          at("composite-parameter-seed").value = "18446744073709551615";
          at("composite-parameter-random").click();
          await waitFor(() => compositeIdle() && !at("composite-instance-result").hidden, "mobile real variant");
          await settledMath("composite-public-template", "composite-presentation-note");
          check(at("composite-public-template").querySelector(".slot-filled"), "Mobile variant has no filled inputs");
          check(at("composite-parameter-seed").value === "18446744073709551615", "Mobile seed input lost digits");
          inside("composite-root-answer");
          noOverflow("filled composite variant and solution");
          inside("composite-copy-current");
          at("atomic-tab").click();
          check(at("atomic-answer-value").textContent === atomicAnswer, "Mobile tabs lost atomic state");
          noOverflow("restored atomic panel");
          return "OK: 390px actual WASM random task, long formula, composite variant and usable seed controls";
        '''
        with static_origin() as server:
            output = run_browser(self.runner, server.url + "__renderer_test__.html", script)
            self.assertIn("OK: 390px actual WASM", output)
            self.assertTrue(any(path.endswith("/worker.js") for _, path in server.requests))
            self.assertTrue(any(path.endswith("/runtime.zip") for _, path in server.requests))
            self.assertFalse(any(method == "POST" or "/api/" in path for method, path in server.requests))


if __name__ == "__main__":
    unittest.main()
