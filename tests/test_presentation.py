"""Display metadata must preserve exact native math and canonical exports."""
from copy import deepcopy
from fractions import Fraction
import re
import unittest

from support import ensure_runtime

ensure_runtime()

from composite_dataset import build_schema, instantiate
from composite_dataset.profiles import get_catalogue
from composite_dataset.schema import canonical
from composite_dataset.smart_adapters import evaluate_adapter
from template_dataset.registry import get_template
from math_demo.api import composite_response as respond
from math_demo.presentation import (
    _adapter_math, _number, _operator_math, _question, _tex_text, presentation,
)


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = build_schema(3, 4, 42)

    def test_preview_and_filled_fragments_preserve_schema_and_native_questions(self):
        original = canonical(self.schema)
        before = presentation(self.schema)
        item = instantiate(self.schema, 2**64-1)
        after = presentation(self.schema, 2**64-1)
        self.assertEqual(canonical(self.schema), original)
        self.assertEqual(before['mode'], 'template')
        self.assertEqual(after['mode'], 'instance')
        native = {n['node_id']: n for n in self.schema['nodes']}
        trace = {row['node_id']: row for row in item['trace']}
        for a, b in zip(before['nodes'], after['nodes']):
            row = trace[a['node_id']]
            self.assertTrue(all(i['text'] is None for i in a['inputs']))
            self.assertTrue(all(type(i['text']) is str for i in b['inputs']))
            expected = get_template(a['source_id']).render(row['parameters'])
            self.assertEqual(''.join(p['text'] for p in b['segments']), expected)
            self.assertEqual(b['answer'], row['answer'])
            self.assertIsNone(a['answer'])
            self.assertTrue(all(p['filled'] for p in b['segments'] if p['kind'] == 'parameter'))
            if a['kind'] == 'internal':
                self.assertTrue(a['adapter_math'])
                self.assertEqual(len(native[a['node_id']]['bindings']), len(b['incoming']))
                for signal, binding in zip(b['incoming'], native[a['node_id']]['bindings']):
                    source_answer = trace[binding['source_node']]['answer']
                    self.assertEqual(signal['answer'], source_answer)
                    self.assertEqual(signal['value'], str(evaluate_adapter(binding['operator'], source_answer)))
                    self.assertEqual(signal['source_node'], binding['source_node'])

    def test_every_catalogue_leaf_profile_reconstructs_both_endpoints(self):
        for source, profiles in get_catalogue().items():
            profile = next((p for p in profiles if p['arity'] == 1), profiles[0])
            node = {'source_id': source, 'profile': profile, 'label': 'R1', 'children': []}
            for params in (profile['rows'][0], profile['rows'][-1]):
                with self.subTest(source=source):
                    parts, notes, scope = _question(node, params)
                    self.assertEqual(''.join(p['text'] for p in parts), get_template(source).render(params))

    def test_presentation_endpoint_uses_null_or_exact_uint64_seed(self):
        route = '/api/composite/presentation'
        self.assertEqual(respond(route, {'schema': self.schema, 'seed': None})['mode'], 'template')
        self.assertEqual(respond(route, {'schema': self.schema, 'seed': str(2**64-1)}), presentation(self.schema, 2**64-1))
        for seed in (True, 42, -1, '', '1e3', str(2**64)):
            with self.subTest(seed=seed):
                with self.assertRaises(ValueError):
                    respond(route, {'schema': self.schema, 'seed': seed})
        bad = deepcopy(self.schema)
        bad['nodes'][0]['arity'] = True
        with self.assertRaises(ValueError):
            respond(route, {'schema': bad, 'seed': None})

    def test_threshold_rendering_uses_actual_less_bit(self):
        op = {'kind': 'select', 'classifier': {'kind': 'threshold', 'cut': '3/2', 'less_bit': 1}, 'target_domain': {'values': [0, 1]}}
        text, notes = _operator_math(op, 'R12')
        self.assertIn(r'\begin{cases}1 & \text{выход №12}<\frac{3}{2}', text)
        self.assertIn(r'\\0 &', text)
        self.assertEqual(notes, [])



def scalar(tex):
    fraction = re.fullmatch(r"(-?)\\frac\{(\d+)\}\{(\d+)\}", tex)
    if fraction:
        sign, numerator, denominator = fraction.groups()
        return Fraction(int((sign or "") + numerator), int(denominator))
    return Fraction(int(tex))


class DisplayedOperatorReviewTests(unittest.TestCase):
    def test_identity_and_affine_display_keep_exact_rational_coefficients(self):
        identity = {
            'kind': 'identity', 'result_type': 'int',
            'source_domain': {'kind': 'finite', 'values': ['0', '1']},
            'target_domain': {'kind': 'finite', 'values': [0, 1]},
        }
        self.assertEqual(_operator_math(identity, 'R27'), (r'\text{выход №27}', []))
        wide = 9007199254740993
        affine = {
            'kind': 'affine', 'result_type': 'int',
            'source_domain': {'kind': 'finite', 'values': [str(wide), str(wide + 3)]},
            'target_domain': {'kind': 'finite', 'values': [1, 0]},
            'scale': '-1/3', 'offset': str(Fraction(wide + 3, 3)),
        }
        tex, notes = _operator_math(affine, 'R27')
        coefficients = re.fullmatch(r'(.*?)\\text\{выход №27\}\+(.*)', tex)
        self.assertIsNotNone(coefficients)
        scale, offset = map(scalar, coefficients.groups())
        for answer, expected in ((wide, 1), (wide + 3, 0)):
            self.assertEqual(scale * answer + offset, expected)
            self.assertEqual(evaluate_adapter(affine, answer), expected)
        self.assertFalse(notes)

    def test_threshold_display_respects_both_orientations_and_equality(self):
        cut = Fraction(-9007199254740993, 7)
        for less_bit in (0, 1):
            op = {
                'kind': 'select', 'source_domain': {'kind': 'rational'},
                'target_domain': {'kind': 'finite', 'values': [0, 1]},
                'classifier': {'kind': 'threshold', 'cut': str(cut), 'less_bit': less_bit},
            }
            tex, _ = _operator_math(op, 'R9')
            branches = re.fullmatch(r'\\begin\{cases\}(.*?) & \\text\{выход №9\}<(.*?)\\\\(.*?) & \\text\{otherwise\}\\end\{cases\}', tex)
            self.assertIsNotNone(branches)
            less, boundary, other = map(scalar, branches.groups())
            self.assertEqual(boundary, cut)
            for answer, expected in ((cut - 1, less_bit), (cut, 1 - less_bit), (cut + 1, 1 - less_bit)):
                self.assertEqual(less if answer < boundary else other, expected)
                self.assertEqual(evaluate_adapter(op, answer), expected)

    def test_floor_mod_display_uses_negative_floor_and_reduced_denominator(self):
        spec = {'op': 'floor_mod', 'numerator': -7, 'denominator': 11,
                'divisor': 4, 'modulus': 7, 'threshold': 3}
        op = {'kind': 'select', 'source_domain': {'kind': 'rational'},
              'target_domain': {'kind': 'finite', 'values': [0, 1]},
              'classifier': {'kind': 'floor_mod', 'spec': spec}}
        tex, notes = _operator_math(op, 'R4')
        parsed_tex = tex.replace(r'\text{числитель}\left(\text{выход №4}\right)', 'N_{4}').replace(
            r'\text{знаменатель}\left(\text{выход №4}\right)', 'D_{4}')
        coefficients = re.search(r'(-?\d+)N_\{4\}\+(-?\d+)D_\{4\}\}\{(\d+)\}\\right\\rfloor,(\d+)\\right\)<(\d+)', parsed_tex)
        self.assertIsNotNone(coefficients)
        a, b, divisor, modulus, threshold = map(int, coefficients.groups())
        self.assertTrue(tex.startswith(r'\begin{cases}0 & '))
        self.assertTrue(tex.endswith(r'\\1 & \text{otherwise}\end{cases}'))
        self.assertIn('сокращённой дроби', ' '.join(notes))
        self.assertIn('положительным знаменателем', ' '.join(notes))
        # Hand-computed cases include floor(-3/4) = -1 and positive residue 6.
        for answer, expected in (('-13/5', 0), ('-1/2', 0), ('2', 1), ('4', 0), ('8/4', 1), ('11/3', 1)):
            q = Fraction(answer)
            residue = ((a * q.numerator + b * q.denominator) // divisor) % modulus
            self.assertEqual(int(residue >= threshold), expected)
            self.assertEqual(evaluate_adapter(op, answer), expected)

    def test_grouped_parity_uses_ports_and_collision_free_signal_names(self):
        wide = 9007199254740993
        rows = [
            {'u1': wide, 'b1': '2/3', 'rate': [1, 2]},
            {'u1': wide + 2, 'b1': '2/3', 'rate': [3, 4]},
            {'u1': wide, 'b1': '-5/7', 'rate': [1, 2]},
            {'u1': wide + 2, 'b1': '-5/7', 'rate': [3, 4]},
        ]
        node = {'profile': {'parameter_names': ['u1', 'b1', 'rate'], 'rows': rows},
                'adapter': {'groups': [[0, 2], [1]]},
                'bindings': [{'input_index': i, 'source_node': str(i), 'operator': {'kind': 'identity'}} for i in range(3)]}
        rules, notes = _adapter_math(node, {str(i): {'label': 'R' + str(i + 1)} for i in range(3)})
        self.assertEqual(rules[:3], [r'\text{\_u1} = \text{выход №1}', r'\text{u2} = \text{выход №2}', r'\text{u3} = \text{выход №3}'])
        self.assertIn(r'\text{\_b1}=\left(\text{\_u1}+\text{u3}\right)\bmod 2', rules)
        self.assertIn(str(wide), rules[4])
        self.assertIn(str(wide + 2), rules[4])
        self.assertIn(r'\text{[1,2]}', rules[4])
        self.assertIn(r'\text{[3,4]}', rules[4])
        self.assertIn(r'\text{\_b1}=0', rules[4])
        self.assertIn(r'\text{2/3}', rules[5])
        self.assertIn(r'\text{-5/7}', rules[5])
        self.assertIn(r'\text{u2}=0', rules[5])
        self.assertFalse(notes)

    def test_display_literals_do_not_round_or_accept_tex_commands(self):
        self.assertEqual(_number(9007199254740993), '9007199254740993')
        self.assertEqual(_number('-9007199254740993/17'), r'-\frac{9007199254740993}{17}')
        encoded = _tex_text(r'}\href{https://invalid}{x} $ % # & _')
        self.assertIn(r'\}\textbackslash{}href\{', encoded)
        self.assertNotIn(r'\href{', encoded)
        self.assertIn(r'\$ \% \# \& \_', encoded)


class StructuralFragmentReviewTests(unittest.TestCase):
    def test_structural_tex_fragments_use_full_native_parameter_patterns(self):
        catalogue = get_catalogue()
        for source in ('algebra/test/341', 'algebra/train/135',
                       'algebra/train/943', 'algebra/train/775'):
            profile = next((p for p in catalogue[source] if p['arity'] == 1), catalogue[source][0])
            node = {'source_id': source, 'profile': profile, 'label': 'R7', 'children': []}
            with self.subTest(source=source):
                preview, notes, scope = _question(node, None)
                self.assertEqual(scope, 'native-fields')
                self.assertTrue(any(part['kind'] == 'parameter' for part in preview))
                self.assertNotIn('fragment', ''.join(part['text'] for part in preview) + ' '.join(notes))
                self.assertNotIn('R7.', ''.join(part['text'] for part in preview))
                for params in profile['rows']:
                    filled, _, filled_scope = _question(node, params)
                    self.assertEqual(filled_scope, 'native-fields')
                    self.assertEqual(''.join(part['text'] for part in filled), get_template(source).render(params))
                    self.assertTrue(all(part['parameters'] for part in filled if part['kind'] == 'parameter'))


    def test_seeded_native_bottoms_reconstruct_with_shared_native_patterns(self):
        catalogue = get_catalogue()
        for source in ('algebra/test/341', 'algebra/train/135',
                       'algebra/train/943', 'algebra/train/775'):
            profile = next((p for p in catalogue[source] if p['arity'] == 1), catalogue[source][0])
            schema = build_schema(1, 1, 0, split=source.split('/')[1], catalogue={source: [profile]})
            for seed in (0, 2**64 - 1):
                with self.subTest(source=source, seed=seed):
                    item = instantiate(schema, seed)
                    rendered = presentation(schema, seed)['nodes'][0]
                    native = get_template(source).render(item['bottom_parameters'][rendered['node_id']])
                    self.assertEqual(''.join(s['text'] for s in rendered['segments']), native)
                    self.assertEqual(rendered['scope'], 'native-fields')
                    self.assertTrue(all(i['role'] == 'external' and i['text'] is not None
                                        for i in rendered['inputs']))


if __name__ == '__main__':
    unittest.main()
