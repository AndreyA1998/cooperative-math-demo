"""Browser regressions for the single-canvas pattern/instance experience."""
import tempfile
import unittest
from support import HAS_BROWSER, prepare_browser, run_browser, static_origin


@unittest.skipUnless(HAS_BROWSER, 'Requires Playwright with Chromium, or native macOS WebKit and Clang')
class VisualStateTests(unittest.TestCase):
    def test_pattern_fill_reset_and_filter_memory_with_real_runtime(self):
        with tempfile.TemporaryDirectory(prefix='math-demo-state-') as folder:
            runner = prepare_browser(folder)
            with static_origin() as server:
                result = run_browser(runner, server.url, r'''
                  check($("atomic-reset"), "Atomic task has no reset to the bare pattern");
                  await until(idleAtomic, "initial bare pattern");
                  check($("atomic-problem-text").querySelector(".parameter-slot, [data-parameters]"), "Initial task has no symbolic slots");
                  const settled = async () => { await until(() => [...document.querySelectorAll(".tab-panel:not([hidden]) .math-fragment")].every(node => node.hasAttribute("data-rendered")) || [...document.querySelectorAll(".tab-panel:not([hidden]) .help:not([hidden])")].some(node => node.textContent.includes("LaTeX")), "typesetting", {timeout: 20000}); };
                  await settled();
                  const originalId = $("atomic-problem-id").value;
                  const originalSubject = $("atomic-subject").value;
                  const originalSplit = $("atomic-split").value;
                  const bare = $("atomic-problem-text").textContent;
                  $("atomic-seed-mode").click();
                  $("atomic-seed").value = "18446744073709551615";
                  $("atomic-generate").click();
                  await until(idleAtomic, "filled task");
                  const filled = $("atomic-problem-text").textContent;
                  const answer = $("atomic-answer-value").textContent;
                  check(filled !== bare && answer && !$("atomic-answer").hidden, "Numbers and answer did not fill the existing task");
                  change("atomic-subject", "algebra");
                  await until(idleAtomic, "other subject");
                  change("atomic-split", "train");
                  await until(idleAtomic, "other split");
                  change("atomic-subject", originalSubject);
                  await until(idleAtomic, "restored subject");
                  change("atomic-split", originalSplit);
                  await until(idleAtomic, "restored split");
                  check($("atomic-problem-id").value === originalId, "Filter switch lost the selected task");
                  check($("atomic-answer-value").textContent === answer && $("atomic-seed").value === "18446744073709551615", "Filter switch lost answer or exact seed");
                  $("composite-tab").click();
                  $("composite-structure-seed-mode").click();
                  $("composite-structure-seed").value = "42";
                  $("composite-depth").value = "3";
                  $("composite-width").value = "4";
                  $("composite-structure-random").click();
                  await until(idleComposite, "bare tree");
                  await settled();
                  const bareTree = $("composite-tree").innerHTML;
                  const bareCards = $("composite-public-template").textContent;
                  check(!/affine|select|(?:train|test)\//.test($("composite-tree").textContent), "Tree exposes implementation labels");
                  const nodeIds = [...$("composite-tree").querySelectorAll("[data-node]")].map(node => node.dataset.node);
                  $("composite-parameter-random").click();
                  await until(idleComposite, "filled tree");
                  check($("composite-tree").innerHTML !== bareTree, "Instantiation did not update the tree");
                  check($("composite-tree").querySelectorAll(".tree-node-answer").length === nodeIds.length, "Some tree nodes lack answers");
                  check($("composite-tree").querySelector(".tree-flow-value"), "Tree edges have no incoming values");
                  check($("composite-public-template").querySelectorAll(".subproblem-answer").length === nodeIds.length, "Cards did not all receive answers");
                  check($("composite-public-template").querySelectorAll(".subproblem-internal .slot-filled").length, "Joint-adapted target parameters remain unfilled");
                  check($("composite-root-answer").getBoundingClientRect().height > 0, "Answer requires a details click");
                  $("atomic-tab").click();
                  check($("atomic-answer-value").textContent === answer, "Tabs lost atomic state");
                  $("atomic-reset").click();
                  await settled();
                  check($("atomic-answer-value").textContent === "—" && $("atomic-problem-text").textContent === bare, "Atomic reset did not restore the pattern");
                  $("composite-tab").click();
                  $("composite-reset-parameters").click();
                  await settled();
                  check($("composite-tree").innerHTML === bareTree, "Reset changed the tree structure");
                  check($("composite-public-template").textContent === bareCards, "Reset changed the symbolic cards");
                  return "OK: exact seeds, filter memory and in-place tree/card values";
                ''')
                self.assertIn('OK:', result)
