"""Adversarial display ownership, independently specified from the problem text.

Text reconstruction alone cannot establish that a highlighted span belongs to a
parameter: a single annotation around the whole statement also reconstructs it.
"""
import tempfile
import unittest

from support import (ensure_runtime, HAS_BROWSER, prepare_browser, run_browser,
                     static_origin)
ensure_runtime()
from math_demo import presentation as display
from template_dataset.registry import generate, registry


def slots(result):
    return [part for part in result['segments'] if part['kind'] == 'parameter']


class SlotOwnershipTests(unittest.TestCase):
    def test_amgm_owns_coefficients_but_not_equal_literal_exponents_or_prose(self):
        source = 'intermediate_algebra/test/200'
        for parameters, values in (
            ({'a': 3, 'b': 2, 'c': '243/2'}, ('3', '2', r'\frac{243}{2}')),
            ({'a': 3, 'b': 3, 'c': 3}, ('3', '3', '3')),
        ):
            with self.subTest(parameters=parameters):
                result = display.atomic_presentation(source, parameters)
                owned = slots(result)
                self.assertEqual([(part['parameters'], part['text']) for part in owned],
                                 [([name], value) for name, value in zip(('a', 'b', 'c'), values)])
                # The exponent 3 occurs three times even when every coefficient
                # also equals 3. Its ownership must not be inferred from digits.
                literal = ''.join(part['text'] for part in result['segments'] if part['kind'] == 'text')
                self.assertIn('For positive real $x,y,z$, find the minimum of', literal)
                self.assertIn('x^3', literal)
                self.assertIn('y^3', literal)
                self.assertIn('z^3', literal)
                self.assertIn('{xyz}', literal)
                self.assertTrue(literal.endswith('.'))

    def test_every_template_has_a_full_bare_condition_and_owned_substitutions(self):
        for source, template in registry().items():
            with self.subTest(source=source):
                bare = display.atomic_presentation(source)
                filled = display.atomic_presentation(source, template.original)
                self.assertEqual(bare['scope'], 'native-fields')
                self.assertEqual(filled['scope'], 'native-fields')
                self.assertTrue(slots(bare), 'a parameter list alone is not a problem template')
                literal = ''.join(part['text'] for part in bare['segments'] if part['kind'] == 'text')
                self.assertRegex(literal, r'[A-Za-z]{2,}', 'the question must be visible before filling')
                self.assertNotIn('statement(', literal)
                self.assertEqual(''.join(part['text'] for part in filled['segments']),
                                 template.render(template.original))
                self.assertEqual([part['key'] for part in slots(bare)],
                                 [part['key'] for part in slots(filled)])
                for part in slots(bare):
                    self.assertFalse(part['filled'])
                    self.assertTrue(part['parameters'], 'a placeholder must own declared inputs')
                    self.assertLessEqual(set(part['parameters']), set(template.parameters))

    def test_filled_parameter_fragments_do_not_own_tex_delimiters_or_cross_groups(self):
        for source in registry():
            for seed in (0, 17, 2**64 - 1):
                item = generate(source, seed)
                result = display.atomic_presentation(source, item['parameters'])
                for part in slots(result):
                    with self.subTest(source=source, seed=seed, field=part['name']):
                        text, depth, index = part['text'], 0, 0
                        # Parse independently of the production _structural_tex
                        # helper. Escaped braces/dollars are literal characters;
                        # TeX delimiters and braces belonging to another fragment
                        # cannot be owned by this parameter.
                        while index < len(text):
                            character = text[index]
                            if character == '\\' and index + 1 < len(text):
                                next_character = text[index + 1]
                                self.assertNotIn(next_character, '()[]',
                                                 'parameter owns a math delimiter')
                                if next_character in '{}$\\':
                                    index += 2
                                    continue
                            elif character == '$':
                                self.fail('parameter owns a math delimiter')
                            elif character == '{':
                                depth += 1
                            elif character == '}':
                                depth -= 1
                                self.assertGreaterEqual(depth, 0, 'parameter closes an external TeX group')
                            index += 1
                        self.assertEqual(depth, 0, 'parameter leaves its TeX group open')

    def test_fraction_and_word_input_values_have_no_serialization_quotes(self):
        for source, parameters, name, expected in (
            ('intermediate_algebra/test/200', {'a': 3, 'b': 2, 'c': '243/2'}, 'c', '243/2'),
            ('counting_and_probability/train/33', {'word': 'BANANA'}, 'word', 'BANANA'),
        ):
            with self.subTest(source=source):
                result = display.atomic_presentation(source, parameters)
                inputs = {item['name']: item['text'] for item in result['inputs']}
                self.assertEqual(inputs[name], expected)

    def test_derived_sequence_terms_have_their_actual_input_dependencies(self):
        source = 'algebra/train/31'
        parameters = {'anchor_numerator': 13, 'anchor_denominator': 2,
                      'step_numerator': -1, 'step_denominator': 2,
                      'first_index': 1, 'second_index': 13, 'target_index': 50}
        result = display.atomic_presentation(source, parameters)
        owned = slots(result)
        # Term 13 is 13/2 + (13-1)*(-1/2) = 1/2. The target index
        # does not enter either given term's value, despite appearing nearby.
        self.assertEqual([part['text'] for part in owned],
                         ['1', r'\frac{13}{2}', '13', r'\frac{1}{2}', '50'])
        self.assertEqual([set(part['parameters']) for part in owned], [
            {'first_index'}, {'anchor_numerator', 'anchor_denominator'}, {'second_index'},
            {'anchor_numerator', 'anchor_denominator', 'second_index', 'first_index',
             'step_numerator', 'step_denominator'}, {'target_index'},
        ])
        changed = slots(display.atomic_presentation(source, dict(parameters, target_index=70)))
        self.assertEqual([part['text'] for part in changed[:-1]], [part['text'] for part in owned[:-1]])
        self.assertEqual(changed[-1]['text'], '70')

    def test_complete_derived_polynomial_is_distinct_from_its_static_prose(self):
        result = display.atomic_presentation('algebra/train/26', {'root_1': 3, 'root_2': 8})
        owned = slots(result)
        # (x-3)(x-8)=x^2-11x+24. A complete safe polynomial fragment can
        # legitimately depend on both roots; surrounding prose cannot.
        self.assertEqual(len(owned), 1)
        self.assertEqual(set(owned[0]['parameters']), {'root_1', 'root_2'})
        self.assertEqual(owned[0]['text'], r'x^{2} - 11x + 24')
        self.assertNotIn('greatest', owned[0]['text'])

    def test_custom_section_operator_is_a_literal_not_an_input(self):
        parameters = {'first_coefficient': 29, 'second_coefficient': 10, 'left': 4, 'right': 13}
        result = display.atomic_presentation('algebra/train/374', parameters)
        self.assertEqual([(part['parameters'], part['text']) for part in slots(result)],
                         [(['first_coefficient'], '29'), (['second_coefficient'], '10'),
                          (['left'], '4'), (['right'], '13')])
        literal = ''.join(part['text'] for part in result['segments'] if part['kind'] == 'text')
        # The source explicitly defines the arbitrary operator \S. It is not a
        # corrupted plus sign; 29*4+10*13 would evaluate to 246.
        self.assertEqual(literal.count(r'\S'), 3)


@unittest.skipUnless(HAS_BROWSER, 'Requires Playwright with Chromium, or native macOS WebKit and Clang')
class SlotOwnershipBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='math-demo-slot-ownership-')
        cls.addClassCleanup(temporary.cleanup)
        cls.runner = prepare_browser(temporary.name)

    def check_browser(self, script):
        with static_origin() as server:
            output = run_browser(self.runner, server.url + '__renderer_test__.html', script, timeout=60)
        self.assertIn('OK', output)

    def test_whole_statement_annotations_cannot_color_prose_across_tex_boundaries(self):
        self.check_browser(r'''
          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          const statement = 'For positive real $x,y,z$, find the minimum of $\\frac{3 x^3+2 y^3+\\frac{243}{2} z^3}{xyz}$.';
          const whole = {kind:'parameter', key:'statement', name:'statement', role:'external', filled:true,
            parameters:['a','b','c'], text:statement};
          const rendered = MathPresentation.render(target, [whole]);
          check(target.querySelectorAll('.parameter-slot').length === 0,
            'A cross-formula statement annotation colored static prose in the fallback');
          check(target.textContent === statement, 'Discarding unsafe emphasis changed the exact fallback text');
          check(await rendered, 'The intact AM-GM formula failed to render');
          check(target.querySelectorAll('.parameter-slot,.fbox').length === 0,
            'Whole-statement ownership leaked into prose or formula boxes');
          check(target.querySelectorAll('.katex').length === 2, 'Both original formulas must still render');
          const text = text => ({kind:'text', text});
          const slot = (key, text) => ({kind:'parameter', key, name:key, text, role:'external', filled:true, parameters:[key]});
          const precise = [text('For positive real $x,y,z$, find the minimum of $\\frac{'),
            slot('a','3'), text(' x^3+'), slot('b','2'), text(' y^3+'),
            slot('c','\\frac{243}{2}'), text(' z^3}{xyz}$.')];
          check(await MathPresentation.render(target, precise), 'Precise coefficient slots broke the formula');
          check(target.querySelectorAll('.fbox').length === 3, 'Exactly the three coefficients must be boxed');
          check(target.querySelectorAll('.parameter-slot').length === 0, 'Static prose acquired a parameter box');
          return 'OK: exact ownership across TeX boundaries';
        ''')

    def test_empty_filled_sign_is_invisible_but_minus_and_named_sign_remain(self):
        self.check_browser(r'''
          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          const present = (value, filled) => [
            {kind:'text', text:'Value $'},
            {kind:'parameter', key:'sign', name:'sign', parameters:['numerator'], role:'external', filled, text:value},
            {kind:'text', text:'\\frac{13}{2}$.'},
          ];
          check(await MathPresentation.render(target, present('', true)), 'Positive fraction failed to render');
          check(target.querySelectorAll('.fbox,.parameter-slot').length === 0,
            'An empty filled sign became a visible empty parameter box');
          check(await MathPresentation.render(target, present('-', true)), 'Negative fraction failed to render');
          check(target.querySelectorAll('.fbox').length === 1, 'A real minus sign lost its ownership box');
          check(await MathPresentation.render(target, present('sign', false)), 'Bare sign slot failed to render');
          check(target.querySelectorAll('.fbox').length === 1 && target.textContent.includes('sign'),
            'The unfilled named sign slot disappeared');
          return 'OK: positive, negative, and unfilled sign ownership';
        ''')


if __name__ == '__main__':
    unittest.main()
