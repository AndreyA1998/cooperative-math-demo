"""Real native renderers keep parameter ownership and exact text across domains."""
import unittest
import json
from urllib.parse import urlencode
from support import ensure_runtime
ensure_runtime()
from template_dataset.registry import generate, get_template, registry
from math_demo import presentation as display
from math_demo.api import dispatch_json


class AtomicPresentationTests(unittest.TestCase):
    def present(self, source, params=None):
        self.assertTrue(hasattr(display, 'atomic_presentation'), 'Atomic presentation is missing')
        return display.atomic_presentation(source, params)

    def test_equal_values_have_distinct_owners_and_do_not_replace_literal_digits(self):
        source = 'prealgebra/test/11'
        filled = self.present(source, {'n1': 12, 'n2': 12, 'n3': 2, 'n4': 1})
        slots = [p for p in filled['segments'] if p['kind'] == 'parameter']
        self.assertEqual([(p['name'], p['text']) for p in slots], [('n1','12'), ('n2','12'), ('n3','2'), ('n4','1')])
        bare = self.present(source)
        self.assertTrue(all(not p['filled'] for p in bare['segments'] if p['kind'] == 'parameter'))
        source = 'algebra/train/1316'
        filled = self.present(source, {'squared_number': 10**35 - 1})
        text = ''.join(p['text'] for p in filled['segments'])
        self.assertTrue(text.startswith('Squaring 99 gives 9801, with one zero.'))
        self.assertEqual(filled['inputs'][0]['text'], str(10**35 - 1))
        self.assertEqual([p['parameters'] for p in filled['segments'] if p['kind'] == 'parameter'], [['squared_number']])

    def test_strings_lists_and_derived_values_keep_explicit_input_ownership(self):
        for source, params in (
            ('counting_and_probability/train/33', {'word': 'BANANA'}),
            ('counting_and_probability/train/253', {'distances': [5000, 5000, 6000, 7000, 8000, 9000], 'threshold': 5000}),
            ('algebra/train/52', {'sum': 20, 'difference': 4}),
            ('algebra/train/56', {'center': 20, 'offset': 2}),
        ):
            with self.subTest(source=source):
                filled = self.present(source, params)
                self.assertEqual(''.join(s['text'] for s in filled['segments']), get_template(source).render(params))
                self.assertEqual({i['name'] for i in filled['inputs']}, set(params))
                self.assertNotEqual(filled['scope'], 'computed-statement')
                self.assertTrue(all(set(s['parameters']) <= set(params) for s in filled['segments'] if s['kind']=='parameter'))

    def test_polynomial_and_rational_formatters_are_exact_derived_slots(self):
        for source in ('algebra/train/26', 'algebra/train/29', 'algebra/train/31', 'algebra/train/34'):
            with self.subTest(source=source):
                bare = self.present(source)
                self.assertEqual(bare['scope'], 'native-fields')
                for seed in (0, 17, 2**64 - 1):
                    item = generate(source, seed)
                    filled = self.present(source, item['parameters'])
                    self.assertEqual(filled['scope'], bare['scope'])
                    self.assertEqual(''.join(p['text'] for p in filled['segments']), item['problem'])

    def test_negative_fraction_exponents_keep_rational_constants_exact(self):
        source = 'prealgebra/train/47'
        params = {'numerator': -62533, 'denominator': 100, 'places': 4}
        filled = self.present(source, params)
        self.assertEqual(filled['scope'], 'native-fields')
        self.assertIn(r'\frac{1}{10000}', ''.join(s['text'] for s in filled['segments']))
        self.assertEqual(''.join(s['text'] for s in filled['segments']), get_template(source).render(params))

    def test_text_rewrite_cannot_turn_a_bare_plus_slot_into_minus_on_fill(self):
        source = 'intermediate_algebra/train/1292'
        bare = self.present(source)
        filled = self.present(source, generate(source, 0)['parameters'])
        self.assertEqual(filled['scope'], bare['scope'])

    def test_percent_formatted_amgm_coefficients_have_their_own_slots(self):
        source = 'intermediate_algebra/test/200'
        params = {'a': 3, 'b': 2, 'c': '243/2'}
        result = self.present(source, params)
        self.assertEqual(result['scope'], 'native-fields')
        slots = [part for part in result['segments'] if part['kind'] == 'parameter']
        self.assertEqual([(part['parameters'], part['text']) for part in slots],
                         [(['a'], '3'), (['b'], '2'), (['c'], r'\frac{243}{2}')])
        self.assertTrue(all('$' not in part['text'] for part in slots))
        self.assertEqual(''.join(part['text'] for part in result['segments']),
                         r'For positive real $x,y,z$, find the minimum of $\frac{3 x^3+2 y^3+\frac{243}{2} z^3}{xyz}$.')

    def test_structural_reciprocal_expression_keeps_prose_literal(self):
        source = 'algebra/train/53'
        for params in (None, generate(source, 17)['parameters']):
            result = self.present(source, params)
            self.assertEqual(result['scope'], 'native-fields')
            literal = ''.join(part['text'] for part in result['segments'] if part['kind'] == 'text')
            self.assertIn('If ', literal)
            self.assertIn('find', literal)
            self.assertTrue(all('If ' not in part['text'] and 'find' not in part['text']
                                for part in result['segments'] if part['kind'] == 'parameter'))

    def test_string_parameter_chips_use_literal_content_without_json_quotes(self):
        for source, params, name, expected in (
            ('intermediate_algebra/test/200', {'a':3, 'b':2, 'c':'243/2'}, 'c', '243/2'),
            ('counting_and_probability/train/33', {'word':'BANANA'}, 'word', 'BANANA'),
        ):
            with self.subTest(source=source):
                result = self.present(source, params)
                value = next(item['text'] for item in result['inputs'] if item['name'] == name)
                self.assertEqual(value, expected)

    def test_semantic_source_bindings_keep_named_native_slots(self):
        # Derived source spans, wrapped equation bindings and both prose span
        # formats use different renderer identity hooks after the package move.
        for source in ('algebra/train/52', 'algebra/train/27',
                       'algebra/train/41', 'algebra/train/4'):
            with self.subTest(source=source):
                item = generate(source, 17)
                result = self.present(source, item['parameters'])
                self.assertEqual(result['scope'], 'native-fields')
                self.assertEqual(''.join(part['text'] for part in result['segments']), item['problem'])
                names = {name for part in result['segments'] if part['kind'] == 'parameter'
                         for name in part['parameters']}
                self.assertEqual(names, set(item['parameters']))

    def test_constructed_alphabet_keeps_length_and_class_owners_separate(self):
        for source in ('counting_and_probability/train/187', 'counting_and_probability/train/251'):
            for params in ({'length': 8, 'vowels': 4, 'consonants': 1},
                           {'length': 2, 'vowels': 1, 'consonants': 8}):
                with self.subTest(source=source, params=params):
                    bare = self.present(source)
                    filled = self.present(source, params)
                    self.assertEqual(bare['scope'], 'native-fields')
                    owned = [p for p in filled['segments'] if p['kind'] == 'parameter']
                    letters = ', '.join(sorted('AEIOU'[:params['vowels']] + 'BCDFGHJK'[:params['consonants']]))
                    self.assertEqual([(set(p['parameters']), p['text']) for p in owned],
                                     [({'length'}, str(params['length'])), ({'vowels', 'consonants'}, letters)])
                    self.assertEqual([p['key'] for p in owned],
                                     [p['key'] for p in bare['segments'] if p['kind'] == 'parameter'])
                    self.assertEqual(''.join(p['text'] for p in filled['segments']), get_template(source).render(params))
                    static = ''.join(p['text'] for p in bare['segments'] if p['kind'] == 'text')
                    self.assertIn('How many ', static)
                    self.assertIn(' contain at least one ', static)
                    self.assertIn('Letters can be reused.', static)

    def test_factorial_sum_full_condition_exists_before_count_is_filled(self):
        source = 'counting_and_probability/train/77'
        bare = self.present(source)
        self.assertEqual(bare['scope'], 'native-fields')
        self.assertIn('units digit', ''.join(p['text'] for p in bare['segments']).lower())
        for count in (4, 274, 500):
            params = {'count': count}
            result = self.present(source, params)
            self.assertEqual(''.join(p['text'] for p in result['segments']), get_template(source).render(params))
            self.assertTrue(any(p['parameters'] == ['count'] for p in result['segments'] if p['kind'] == 'parameter'))

    def test_composite_uses_independent_decimal_owners_without_service_labels(self):
        source = 'prealgebra/train/436'
        node = {'source_id': source, 'label': 'R4', 'children': []}
        bare, notes, scope = display._question(node, None)
        self.assertEqual(scope, 'native-fields')
        self.assertNotIn('R4.', ''.join(part['text'] for part in bare))
        self.assertNotIn('fragment', ''.join(part['text'] for part in bare) + ' '.join(notes))
        filled, _, _ = display._question(node, {'n1': 4, 'n2': 19})
        owned = [part for part in filled if part['kind'] == 'parameter']
        self.assertEqual([(part['parameters'], part['text']) for part in owned],
                         [(['n1'], '0.4'), (['n2'], '1.9')])
        self.assertTrue(all(part['key'].startswith('R4.') for part in owned))
        self.assertEqual(''.join(part['text'] for part in filled), get_template(source).render({'n1': 4, 'n2': 19}))

    def test_conditional_distance_units_keep_both_complete_bare_questions(self):
        source = 'number_theory/train/523'
        bare = self.present(source)
        literal = ''.join(part['text'] for part in bare['segments'] if part['kind'] == 'text')
        self.assertIn('Each course is 26 miles', literal)
        self.assertIn('A course measures 26 large units', literal)
        for unit in (1760, 2000):
            params = {'yards': 385, 'unit': unit, 'trips': 10}
            filled = self.present(source, params)
            self.assertEqual(''.join(part['text'] for part in filled['segments']), get_template(source).render(params))
            self.assertTrue(all('course' not in part['text'] for part in filled['segments'] if part['kind'] == 'parameter'))

    def test_all_supported_domains_reconstruct_ordinary_generation(self):
        for source in registry():
            with self.subTest(source=source):
                status, raw = dispatch_json('GET', '/api/template', urlencode({'id': source}))
                self.assertEqual(status, 200, raw)
                bare = json.loads(raw)['presentation']
                self.assertTrue(bare['segments'])
                self.assertEqual({i['name'] for i in bare['inputs']}, set(get_template(source).parameters))
                self.assertTrue(all(i['text'] is None for i in bare['inputs']))
                for seed in (0, 17, 2**64 - 1):
                    status, raw = dispatch_json('GET', '/api/generate', urlencode({'id': source, 'seed': str(seed)}))
                    self.assertEqual(status, 200, raw)
                    item = json.loads(raw)
                    filled = item['presentation']
                    self.assertEqual(''.join(s['text'] for s in filled['segments']), item['problem'])
                    self.assertEqual(filled['scope'], bare['scope'])
                    self.assertTrue(all(isinstance(i['text'], str) for i in filled['inputs']))

if __name__ == '__main__':
    unittest.main()
