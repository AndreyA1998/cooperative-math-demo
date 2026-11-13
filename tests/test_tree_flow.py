"""Real browser regression: intermediate signals are not final joint parameters."""
import json
import tempfile
import unittest

from support import HAS_BROWSER, ensure_runtime, prepare_browser, run_browser, static_origin

ensure_runtime()
from math_demo.api import dispatch_json


def native(path, body):
    status, raw = dispatch_json("POST", "/api/composite/" + path, "", body)
    if status != 200:
        raise AssertionError(raw)
    return raw, json.loads(raw)


@unittest.skipUnless(HAS_BROWSER, "Requires Playwright with Chromium, or native macOS WebKit and Clang")
class TreeFlowTests(unittest.TestCase):
    def test_answer_signal_and_joint_target_values_are_distinct_visible_stages(self):
        # Search native schemas, so a sampler change cannot silently remove the
        # adversarial joint group from this browser fixture.
        for seed in range(64):
            raw, schema = native("build", json.dumps({"depth": 3, "width": 8, "seed": str(seed),
                "split": "train", "allow_template_reuse": False}))
            joint = [node for node in schema["nodes"] if node["children"]
                     and any(len(group) > 1 for group in node["adapter"]["groups"])]
            if joint:
                break
        else:
            self.fail("No joint-group fixture found in 64 deterministic trees")
        _, variant = native("variant", '{"schema":' + raw + ',"seed":"17"}')
        displays = {node["node_id"]: node for node in variant["presentation"]["nodes"]}
        rows = {row["node_id"]: row for row in variant["instance"]["trace"]}
        numbers = {node["node_id"]: node["number"] for node in schema["nodes"]}
        ports = []
        for node in schema["nodes"]:
            for incoming in displays[node["node_id"]]["incoming"]:
                name = incoming["input_name"]
                # Obtain final values from the executed native trace, separately
                # from presentation.inputs and the intermediate signal values.
                value = rows[node["node_id"]]["parameters"][name]
                final = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                ports.append({"parent": node["node_id"], "source": incoming["source_node"],
                    "number": numbers[incoming["source_node"]], "index": incoming["input_index"],
                    "name": name, "signal": incoming["signal_name"], "answer": incoming["answer"],
                    "value": incoming["value"], "final": final})
        joint_ids = {node["node_id"] for node in joint}
        self.assertTrue(any(port["parent"] in joint_ids and port["final"] != port["value"] for port in ports),
                        "Fixture would not distinguish final joint parameters from raw signal bits")
        expected = {"seed": str(seed), "ports": ports, "nodes": len(schema["nodes"]),
                    "width": schema["actual_width"], "answer": variant["instance"]["answer"]}
        with tempfile.TemporaryDirectory(prefix="math-demo-flow-") as folder:
            runner = prepare_browser(folder)
            with static_origin() as server:
                output = run_browser(runner, server.url + "#composite", "const expected = " + json.dumps(expected) + r''';
                  await until(idleAtomic, "runtime ready");
                  $("composite-structure-seed-mode").click();
                  $("composite-structure-seed").value = expected.seed;
                  $("composite-width").value = "8";
                  $("composite-structure-random").click();
                  await until(idleComposite, "joint schema");
                  const tree = $("composite-tree");
                  const cards = $("composite-public-template");
                  const viewport = $("composite-tree-viewport");
                  const stages = filled => {
                    check(tree.querySelectorAll(".tree-edge-target").length === expected.ports.length, "A target parameter port is missing");
                    check(tree.querySelectorAll(".tree-flow-value").length === expected.ports.length, "An answer/signal stage is missing");
                    for (const port of expected.ports) {
                      const selector = '[data-target="' + port.parent + '"][data-input-index="' + port.index + '"]';
                      const target = tree.querySelector(".tree-edge-target" + selector);
                      const signal = tree.querySelector(".tree-flow-value" + selector);
                      const finalText = port.name + (filled ? " = " + port.final : "");
                      const signalText = "Ans(" + port.number + ")" + (filled ? " = " + port.answer : "") + " → " + port.signal + (filled ? " = " + port.value : "");
                      check(target.dataset.parameter === port.name && target.dataset.value === (filled ? port.final : ""), "Final target uses a signal or the wrong joint coordinate");
                      check(target.textContent === finalText, "Target parameter is truncated or altered");
                      check(signal.dataset.signalName === port.signal && signal.dataset.value === (filled ? port.value : ""), "Signal label/value differs from the adapter");
                      check(signal.textContent === signalText, "Source answer or named intermediate signal is missing");
                      check(Number(target.querySelector("rect").getAttribute("rx")) <= 3, "Final parameter is not in a rectangular label");
                      const targetBox = target.getBoundingClientRect(), signalBox = signal.getBoundingClientRect();
                      check(targetBox.bottom + 8 <= signalBox.top, "Before/after adapter labels overlap");
                      const parent = tree.querySelector('[data-node="' + port.parent + '"]').getBoundingClientRect();
                      const child = tree.querySelector('[data-node="' + port.source + '"]').getBoundingClientRect();
                      check(targetBox.top >= parent.bottom && signalBox.bottom <= child.top, "Edge labels overlap task vertices");
                      const line = cards.querySelector('[data-card-node="' + port.parent + '"] .flow-item[data-input-index="' + port.index + '"]');
                      check(line.querySelector(".flow-source").textContent === "Ans(" + port.number + ")", "Card uses a different answer reference");
                      check(line.querySelector(".flow-target").textContent === finalText, "Card target differs from the tree or executed input");
                    }
                    check([...tree.querySelectorAll(".tree-edge-target tspan, .tree-flow-value tspan")].every(line => line.getComputedTextLength() <= 178), "A long exact edge value overflows its label");
                    const boxes = [...tree.querySelectorAll(".tree-edge-target, .tree-flow-value")].map(node => node.getBoundingClientRect());
                    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
                      const a = boxes[i], b = boxes[j];
                      check(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top, "Different edge labels overlap");
                    }
                  };
                  stages(false);
                  check(!$("composite-instance-result").hidden && $("composite-root-answer").textContent === "—", "Bare root answer lacks a dash");
                  check(cards.querySelectorAll(".subproblem-answer strong").length === expected.nodes && [...cards.querySelectorAll(".subproblem-answer strong")].every(node => node.textContent === "—"), "Bare card answers lack dashes");
                  check($("composite-schema-meta").textContent.includes(expected.width + " агент"), "Actual width is absent");
                  check($("composite-copy-current").parentElement === $("composite-download").parentElement && $("composite-copy-current").closest(".tree-card .section-heading"), "Copy is not adjacent to the top download");
                  check(!cards.textContent.includes("mod(a, m)") && !cards.textContent.includes("сокращённой дроби с положительным знаменателем") && !cards.textContent.includes("округление вниз"), "Generic adapter explanations remain visible");
                  const bareTree = tree.innerHTML;
                  $("composite-parameter-seed-mode").click();
                  $("composite-parameter-seed").value = "17";
                  viewport.scrollTop = 180;
                  const pan = [viewport.scrollLeft, viewport.scrollTop];
                  $("composite-parameter-random").click();
                  await until(idleComposite, "joint values");
                  stages(true);
                  check($("composite-root-answer").textContent === expected.answer, "Root answer changed");
                  check(viewport.scrollLeft === pan[0] && viewport.scrollTop === pan[1], "Filling reset manual tree pan");
                  check(parseFloat(getComputedStyle($("composite-root-answer")).fontSize) >= 20, "Answer is still too small");
                  $("composite-reset-parameters").click();
                  stages(false);
                  check(tree.innerHTML === bareTree, "Reset changed the bare flow labels or tree");
                  check(viewport.scrollLeft === pan[0] && viewport.scrollTop === pan[1], "Reset changed manual tree pan");
                  return "OK: native joint-group answer, intermediate signal and final target ports stay distinct";
                ''')
                self.assertIn("OK:", output)


if __name__ == "__main__":
    unittest.main()
