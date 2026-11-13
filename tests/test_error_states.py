"""Independent UI review: failure recovery and honest structural fallbacks."""
import tempfile
import unittest
from support import HAS_BROWSER, prepare_browser, run_browser, static_origin

FAULT_INJECTION = r'''
  const originalPost = Worker.prototype.postMessage;
  let failNextPath = null;
  Worker.prototype.postMessage = function(message, ...rest) {
    if (message.path === failNextPath) {
      failNextPath = null;
      queueMicrotask(() => this.dispatchEvent(new MessageEvent("message", {data: {
        id: message.id, status: 500, raw: JSON.stringify({error: "Injected one-off API failure"})
      }})));
      return;
    }
    return originalPost.call(this, message, ...rest);
  };
'''


@unittest.skipUnless(HAS_BROWSER, 'Requires Playwright with Chromium, or native macOS WebKit and Clang')
class FrontendErrorStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='math-demo-error-states-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.runner = prepare_browser(cls.temporary.name)

    def run_case(self, script):
        with static_origin() as server:
            return run_browser(self.runner, server.url + "?id=prealgebra/test/11", FAULT_INJECTION + script)

    def test_failed_template_selection_can_fill_current_task_without_reselection(self):
        output = self.run_case(r'''
          await until(idleAtomic, "initial template");
          $("atomic-generate").click();
          await until(idleAtomic, "initial filled task");
          const previousAnswer = $("atomic-answer-value").textContent;
          const previous = $("atomic-problem-id").value;
          const chosen = [...$("atomic-problem-id").options].find(option => option.value !== previous).value;
          failNextPath = "/api/template";
          change("atomic-problem-id", chosen);
          await until(() => !$("atomic-catalogue-controls").disabled && $("atomic-status").classList.contains("error"), "one-off template failure", {allowError: true});
          check($("atomic-reset").disabled && $("atomic-copy").disabled, "A failed selection left actions bound to the previous visible task");
          $("atomic-generate").click();
          await until(() => !$("atomic-catalogue-controls").disabled, "retry fill", {allowError: true});
          check($("atomic-status").hidden, "Fill did not recover after template failure: " + $("atomic-status").textContent);
          check($("atomic-problem-title").textContent === "Задача", "Card title leaks the source task number");
          check(new URL(location.href).searchParams.get("id") === chosen && $("atomic-problem-id").value === chosen, "Recovered card belongs to the old task");
          const {request} = await import("./transport.js");
          const expected = await request("GET", "/api/generate", new URLSearchParams({id: chosen, seed: new URL(location.href).searchParams.get("seed")}).toString());
          check($("atomic-answer-value").textContent === expected.data.answer, "Recovered answer belongs to the old task");
          check($("atomic-answer-value").textContent !== "—", "Recovered task has no answer");
          change("atomic-problem-id", previous);
          await until(idleAtomic, "previous cached task");
          check($("atomic-answer-value").textContent === previousAnswer, "Recovery discarded the previous task state");
          return "OK: failed template selection recovers in place";
        ''')
        self.assertIn('OK:', output)

    def test_reset_after_template_presentation_failure_removes_all_filled_answers(self):
        output = self.run_case(r'''
          await until(idleAtomic, "initial template");
          $("composite-tab").click();
          $("composite-structure-seed-mode").click();
          $("composite-structure-seed").value = "42";
          failNextPath = "/api/composite/presentation";
          $("composite-structure-random").click();
          await until(idleComposite, "schema with failed optional presentation");
          check(!$("composite-presentation-note").hidden, "Optional presentation failure was not exercised");
          $("composite-parameter-random").click();
          await until(idleComposite, "filled schema");
          check($("composite-public-template").querySelector(".subproblem-answer"), "Variant has no visible node answers");
          $("composite-reset-parameters").click();
          await until(idleComposite, "reset after presentation failure");
          check(!$("composite-public-template").querySelector(".slot-filled, .subproblem-answer"), "Reset left filled values or answers under the bare tree");
          check(!$("composite-instance-result").hidden && $("composite-root-answer").textContent === "—", "Reset must replace the root answer with a visible dash");
          return "OK: reset restores bare state after optional presentation failure";
        ''')
        self.assertIn('OK:', output)

    def test_structural_pattern_is_visible_before_fill_and_after_reset(self):
        output = self.run_case(r'''
          await until(idleAtomic, "initial template");
          change("atomic-subject", "algebra");
          await until(idleAtomic, "algebra subject");
          change("atomic-split", "train");
          await until(idleAtomic, "training split");
          change("atomic-problem-id", "algebra/train/53");
          await until(idleAtomic, "structural pattern");
          const {request} = await import("./transport.js");
          const template = await request("GET", "/api/template", "id=algebra%2Ftrain%2F53");
          check(template.data.presentation.scope !== "computed-statement", "Review fixture still hides its structural condition");
          const settled = async () => until(() => !$("atomic-renderer-note").hidden ||
            [...$("atomic-problem-text").querySelectorAll(".math-fragment")].every(node => node.hasAttribute("data-rendered")), "math layout", {timeout: 20000});
          await settled();
          const bareText = $("atomic-problem-text").textContent;
          check(!bareText.includes("statement("), "Internal statement(...) pseudoformula leaked into the main condition");
          check(bareText.includes("If") && !bareText.includes("после заполнения параметров"), "Structural pattern is not visible before filling");
          check($("atomic-problem-text").querySelector(".parameter-slot, [data-parameters]"), "Structural condition has no symbolic slots");
          check($("atomic-params").querySelectorAll(".input-chip").length > 0, "Structural pattern hid its named inputs");
          $("atomic-generate").click();
          await until(idleAtomic, "filled structural task");
          await settled();
          check($("atomic-problem-text").textContent !== bareText && $("atomic-answer-value").textContent !== "—", "Structural fallback did not fill its real condition and answer");
          $("atomic-reset").click();
          await settled();
          check($("atomic-problem-text").textContent === bareText, "Reset changed the complete structural pattern");
          return "OK: complete structural pattern stays visible before fill and after reset";
        ''')
        self.assertIn('OK:', output)

if __name__ == '__main__':
    unittest.main()
