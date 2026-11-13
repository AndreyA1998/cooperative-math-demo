"""Native derived spans expose formulas, never numbered implementation aliases."""
from fractions import Fraction
import unittest
from support import ensure_runtime
ensure_runtime()
from math_demo.source_bindings import bind_source
from template_dataset.registry import get_template, generate


class NumberedAliasDisplayTests(unittest.TestCase):
    def test_linked_quotient_coefficients_are_explicit_exact_formulas(self):
        for source in ('intermediate_algebra/train/458', 'intermediate_algebra/test/562'):
            template = get_template(source)
            parts = bind_source(template)
            self.assertTrue(parts, source)
            fields = [part for part in parts if not isinstance(part, str)]
            bare = ''.join(part if isinstance(part, str) else part.symbolic_math for part in parts)
            self.assertNotRegex(bare, r'expression \d|formula\(|int\(')
            self.assertIn(r'\text{divisor\_slope}', bare)
            self.assertIn(r'\frac', bare)
            for parameters in (template.original, *(generate(source, seed)['parameters'] for seed in (0, 17, 2**64-1))):
                self.assertEqual(''.join(part if isinstance(part, str) else part.fill(parameters) for part in parts), template.render(parameters))
                p = parameters
                a, b = p['divisor_slope'], p['divisor_constant']
                if source.endswith('/458'):
                    expected = [a, a*p['quotient_linear']-b,
                                b*p['quotient_linear']-Fraction(a*p['quotient_num'], p['quotient_den']),
                                p['dividend_constant'], a, b, p['quotient_linear'], p['quotient_num'], p['quotient_den']]
                else:
                    expected = [a*p['quotient_lead'], p['dividend_quadratic'],
                                Fraction(b*p['quotient_lead']-p['dividend_quadratic'], a)*(Fraction(a*p['ratio_num'], p['ratio_den'])+b),
                                p['dividend_constant'], a, b, p['quotient_lead'], p['ratio_num'], p['ratio_den']]
                self.assertEqual([Fraction(part.fill(p).strip('{}').replace(',', '')) for part in fields], expected)

    def test_modular_sequence_uses_its_defined_terms_and_shifted_indices(self):
        source = 'intermediate_algebra/test/722'
        template = get_template(source)
        parts = bind_source(template)
        self.assertTrue(parts)
        fields = [part for part in parts if not isinstance(part, str)]
        bare = ''.join(part if isinstance(part, str) else part.symbolic_math for part in parts)
        self.assertIn('F_{5}', bare)
        self.assertIn(r'\text{start\_index}+7', bare)
        self.assertNotRegex(bare, r'expression \d|formula\(|values\(')
        for p in (template.original, *(generate(source, seed)['parameters'] for seed in (0, 17, 2**64-1))):
            sequence = [p['first'], p['second']]
            for _ in range(4):
                sequence.append(sum(sequence[-2:]) % p['modulus'])
            expected = [p['first'], p['second'], p['modulus'], *sequence, *range(p['start_index'], p['start_index']+8)]
            self.assertEqual([int(part.fill(p).strip('{}').replace(',', '')) for part in fields], expected)
            self.assertEqual(''.join(part if isinstance(part, str) else part.fill(p) for part in parts), template.render(p))
