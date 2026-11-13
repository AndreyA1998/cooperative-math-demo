"""Read every shipped joint rule as mathematics, independently of execution ASTs."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from support import ensure_runtime
ensure_runtime()
from composite_dataset.profiles import get_catalogue
from composite_dataset.rendering import _render_inputs
from math_demo.presentation import _adapter_math
import test_adapter_consistency as independent
from test_adapter_consistency import plain_rules, pretty_rules


class CompleteAdapterTextTests(unittest.TestCase):
    def test_every_profile_row_and_every_child_port_from_printed_rules(self):
        identity = {'kind': 'identity', 'result_type': 'int',
                    'source_domain': {'kind': 'finite', 'values': ['0', '1']},
                    'target_domain': {'kind': 'finite', 'values': [0, 1]}}
        profile_count = row_count = port_count = 0
        catalogue = get_catalogue()
        self.assertEqual(len(catalogue), 4286)
        for source, profiles in sorted(catalogue.items()):
            for profile in profiles:
                names, rows = profile['parameter_names'], profile['rows']
                # This interpretation of group ownership is independent of the
                # production _joint_adapter/runtime row-index implementation.
                groups = [[names.index(name) for name in group] for group in profile['groups']]
                node = {'profile': profile, 'adapter': {'groups': groups},
                        'bindings': [{'input_index': i, 'source_node': str(i), 'operator': identity}
                                     for i in range(len(names))]}
                children = {str(i): {'label': 'R' + str(i + 1), 'number': i + 1}
                            for i in range(len(names))}
                plain = _render_inputs(node, children)
                pretty, _ = _adapter_math(node, children)
                signals = []
                for index in range(len(rows)):
                    bits = [0] * len(names)
                    for axis, group in enumerate(groups):
                        bits[group[0]] = (index >> axis) & 1
                    signals.append((bits, rows[index]))
                # Also change every nonrepresentative child, including groups
                # with many ports. One child is never split between coordinates.
                for port in range(len(names)):
                    bits = [0] * len(names); bits[port] = 1
                    axis = next(i for i, group in enumerate(groups) if port in group)
                    signals.append((bits, rows[1 << axis]))
                for bits, expected in signals:
                    answers = {'R' + str(i + 1): bit for i, bit in enumerate(bits)}
                    # A rational parameter may use int in one row and str in another.
                    # Read the branch's declared types, never its expected values.
                    types = {name: type(value) for name, value in expected.items()}
                    try:
                        decoded = (plain_rules(plain, answers), pretty_rules(pretty, answers, types))
                        for values in decoded:
                            actual = {name: values[name] for name in names}
                            self.assertEqual(actual, expected)
                            self.assertEqual({name: type(values[name]) for name in names},
                                             {name: type(expected[name]) for name in names})
                    except Exception as error:
                        self.fail(f'{source}, groups={groups}, signals={bits}: {error}')
                profile_count += 1; row_count += len(rows); port_count += len(names)
        self.assertEqual((profile_count, row_count), (10190, 86796))
        self.assertGreater(port_count, 30000)

    def test_independent_readers_detect_wrong_negative_rounding_and_threshold_equality(self):
        checker = independent.AdapterConsistencyTests()
        negative = {'kind': 'select', 'source_domain': {'kind': 'rational'},
                    'target_domain': {'kind': 'finite', 'values': [0, 1]},
                    'classifier': {'kind': 'floor_mod', 'spec': {
                        'op': 'floor_mod', 'numerator': 1, 'denominator': 0,
                        'divisor': 4, 'modulus': 5, 'threshold': 2}}}
        threshold = {'kind': 'select', 'source_domain': {'kind': 'rational'},
                     'target_domain': {'kind': 'finite', 'values': [0, 1]},
                     'classifier': {'kind': 'threshold', 'cut': '7/3', 'less_bit': 0}}
        # Both mutations produce0 where the hand arithmetic gives1. The same
        # comparison helper must fail rather than agreeing with a broken solver.
        for op, answer in ((negative, '-3'), (threshold, '7/3')):
            with self.subTest(answer=answer), patch('test_adapter_consistency.evaluate_adapter', return_value=0):
                with self.assertRaises(AssertionError):
                    checker.assert_representations(deepcopy(op), [answer])
