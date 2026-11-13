"""Independent expected mathematical notation for compact adapter rules."""
import unittest
from support import ensure_runtime
ensure_runtime()
from math_demo.presentation import _operator_math


class OperatorNotationTests(unittest.TestCase):
    def modular(self, numerator, denominator, divisor):
        return {'kind': 'select', 'target_domain': {'values': [0, 1]},
                'classifier': {'kind': 'floor_mod', 'spec': {
                    'numerator': numerator, 'denominator': denominator,
                    'divisor': divisor, 'modulus': 2, 'threshold': 1}}}

    def test_user_case_is_floor_of_half_the_numerator(self):
        formula, notes = _operator_math(self.modular(1, 0, 2), 'R5')
        self.assertIn(r'\left\lfloor\frac{\operatorname{numerator}\left(\operatorname{Ans}(5)\right)}{2}\right\rfloor', formula)
        self.assertNotIn('знаменатель', formula)
        self.assertNotIn('N_{', formula)
        self.assertNotIn('R_{', formula)
        self.assertTrue(any('округление вниз' in note for note in notes))
        self.assertTrue(any('сокращённой дроби' in note for note in notes))

    def test_integer_expression_needs_no_floor_and_keeps_negative_signs(self):
        formula, notes = _operator_math(self.modular(-1, 2, 1), 'R5')
        self.assertIn(r'\operatorname{mod}\left(-\operatorname{numerator}\left(\operatorname{Ans}(5)\right)+2\operatorname{denominator}\left(\operatorname{Ans}(5)\right),2\right)<1', formula)
        self.assertNotIn('floor', formula)
        self.assertFalse(any('округление вниз' in note for note in notes))

    def test_affine_rules_preserve_rationals_and_remove_redundant_factors(self):
        for scale, offset, expected in (
            (1, 0, r'\operatorname{Ans}(5)'),
            (-1, -3, r'-\operatorname{Ans}(5)-3'),
            ('1/2', '5/3', r'\frac{1}{2}\operatorname{Ans}(5)+\frac{5}{3}'),
            (0, 0, '0'),
        ):
            with self.subTest(scale=scale, offset=offset):
                formula, notes = _operator_math({'kind': 'affine', 'scale': scale, 'offset': offset}, 'R5')
                self.assertEqual(formula, expected)
                self.assertEqual(notes, [])
