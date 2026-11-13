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
            return run_browser(self.runner, server.url, FAULT_INJECTION + script)

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
          check($("atomic-problem-title").textContent.includes(chosen.split("/").at(-1)), "Recovered card belongs to the old task");
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
          check($("composite-instance-result").hidden, "Reset left the root answer visible");
          return "OK: reset restores bare state after optional presentation failure";
        ''')
        self.assertIn('OK:', output)

    def test_structural_fallback_explains_blank_condition_without_pseudoformula(self):
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
          check(template.data.presentation.scope === "computed-statement", "Review fixture must exercise a structural fallback");
          const bareText = $("atomic-problem-text").textContent;
          check(!bareText.includes("statement("), "Internal statement(...) pseudoformula leaked into the main condition");
          check(bareText.includes("после заполнения параметров"), "Structural fallback has no visible explanation");
          check($("atomic-params").querySelectorAll(".input-chip").length > 0, "Structural fallback hid its named inputs");
          $("atomic-generate").click();
          await until(idleAtomic, "filled structural task");
          check($("atomic-problem-text").textContent !== bareText && $("atomic-answer-value").textContent !== "—", "Structural fallback did not fill its real condition and answer");
          $("atomic-reset").click();
          check($("atomic-problem-text").textContent === bareText, "Structural fallback reset changed its explanation");
          return "OK: structural fallback stays explicit before and after fill";
        ''')
        self.assertIn('OK:', output)

if __name__ == '__main__':
    unittest.main()
