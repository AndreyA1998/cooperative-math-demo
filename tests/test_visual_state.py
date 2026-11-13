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
                result = run_browser(runner, server.url + "?id=prealgebra/test/11", r'''
                  check($("atomic-reset"), "Atomic task has no reset to the bare pattern");
                  await selectAtomic("prealgebra/test/11");
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
                  check(!$("atomic-download").hidden && $("atomic-download").textContent === "Скачать шаблон", "Atomic reset failed to restore template download");
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

    def test_large_asymmetric_tree_starts_at_root_and_keeps_manual_pan_on_fill(self):
        with tempfile.TemporaryDirectory(prefix='math-demo-tree-viewport-') as folder:
            runner = prepare_browser(folder)
            with static_origin() as server:
                result = run_browser(runner, server.url + "?id=prealgebra/test/11", r'''
                  await until(idleAtomic, "initial runtime");
                  $("composite-tab").click();
                  $("composite-structure-seed-mode").click();
                  $("composite-structure-seed").value = "42";
                  $("composite-depth").value = "12";
                  $("composite-width").value = "128";
                  const viewport = $("composite-tree-viewport");
                  const rootIsVisible = label => {
                    const frame = viewport.getBoundingClientRect();
                    const root = $("composite-tree").querySelector(".tree-root").getBoundingClientRect();
                    const left = frame.left + viewport.clientLeft;
                    const top = frame.top + viewport.clientTop;
                    check(root.left >= left - 1 && root.right <= left + viewport.clientWidth + 1 &&
                          root.top >= top - 1 && root.bottom <= top + viewport.clientHeight + 1,
                          label + ": root is outside the tree viewport");
                    check(Math.abs(root.left + root.width / 2 - left - viewport.clientWidth / 2) <= 1,
                          label + ": viewport is not centered on the root");
                  };
                  const panIs = (position, label) => {
                    check(Math.abs(viewport.scrollLeft - position[0]) <= 1 &&
                          Math.abs(viewport.scrollTop - position[1]) <= 1,
                          label + ": changed the user's tree pan");
                  };
                  $("composite-structure-random").click();
                  await until(idleComposite, "large asymmetric schema");
                  check($("composite-tree").querySelectorAll(".tree-node").length > 128,
                        "Regression did not build the requested large tree");
                  rootIsVisible("new schema");
                  const tree = $("composite-tree");
                  const externalCount = tree.querySelectorAll(".tree-external-input").length;
                  check(tree.querySelectorAll(".tree-external-inputs").length === 128 && externalCount >= 128,
                        "Large tree omitted leaf input panels");
                  const bareInputs = [...tree.querySelectorAll(".tree-external-input")].map(input => input.textContent);
                  const initialPan = [viewport.scrollLeft, viewport.scrollTop];
                  $("composite-parameter-seed-mode").click();
                  $("composite-parameter-seed").value = "17";
                  $("composite-parameter-random").click();
                  await until(idleComposite, "large filled tree");
                  rootIsVisible("filled schema");
                  check(tree.querySelectorAll(".tree-external-filled").length === externalCount,
                        "Large tree left external input values unfilled");
                  check([...tree.querySelectorAll(".tree-external-filled")].every(input => input.textContent.includes(input.dataset.value)),
                        "Large tree clipped an external input value from its SVG text");
                  check([...tree.querySelectorAll(".tree-external-label tspan")].every(line => line.getComputedTextLength() <= 178),
                        "External input text overflows its chip");
                  panIs(initialPan, "initial fill");
                  viewport.scrollLeft += 347;
                  viewport.scrollTop = 243;
                  const manualPan = [viewport.scrollLeft, viewport.scrollTop];
                  check(manualPan[1] > 0, "Regression did not pan the tall tree");
                  $("composite-parameter-random").click();
                  await until(idleComposite, "refill after manual pan");
                  panIs(manualPan, "refill");
                  $("composite-reset-parameters").click();
                  panIs(manualPan, "reset");
                  check(!tree.querySelector(".tree-external-filled") &&
                        JSON.stringify([...tree.querySelectorAll(".tree-external-input")].map(input => input.textContent)) === JSON.stringify(bareInputs),
                        "Large tree reset failed to restore external input names");
                  $("composite-structure-random").click();
                  await until(idleComposite, "replacement schema");
                  rootIsVisible("replacement schema");
                  check(viewport.scrollTop === 0, "Replacement schema kept an old vertical pan");
                  return "OK: large asymmetric root visible; fill/reset preserve manual pan";
                ''')
                self.assertIn('OK:', result)
