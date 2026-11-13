"""Compact TeX arguments and sign formatters keep their mathematical owners."""
from fractions import Fraction
from itertools import product
import re
import unittest
from support import ensure_runtime
ensure_runtime()
from math_demo.source_bindings import bind_source
from math_demo.presentation import atomic_presentation
from template_dataset.registry import get_template,generate

class SourceFractionDisplayTests(unittest.TestCase):
    def test_compact_fraction_has_separate_native_tex_argument_owners(self):
        for source in ('algebra/test/741','algebra/train/95','algebra/train/1022'):
            template=get_template(source);parts=bind_source(template)
            self.assertTrue(parts,source)
            fields=[p for p in parts if not isinstance(p,str)]
            expected_owners=[('x',),('neg_y',),('slope_numerator',),('slope_denominator',)] if source.endswith('/741') else [('shift',),('denominator',)]
            self.assertEqual([p.names for p in fields],expected_owners)
            bare=''.join(v if isinstance(v,str) else (v.symbolic_math or v.label()) for v in parts)
            expected=(r'\frac{\text{slope\_numerator}}{\text{slope\_denominator}}' if source.endswith('/741') else r'\frac1{\text{denominator}}')
            self.assertIn(expected,bare.replace(r'\frac ',r'\frac'))
            for p in (template.original,*(generate(source,s)['parameters'] for s in (0,17,2**64-1))):
                native=template.render(p)
                self.assertEqual(''.join(v if isinstance(v,str) else v.fill(p) for v in parts),native)
                numerator,denominator=map(int,re.search(r'\\frac\s*(\d)(\d)',native).groups())
                self.assertEqual(Fraction(numerator,denominator),Fraction(p.get('slope_numerator',1),p.get('slope_denominator',p.get('denominator'))))
                shown=atomic_presentation(source,p)
                self.assertEqual(''.join(v['text'] for v in shown['segments']),native)
                for owner in expected_owners:
                    self.assertTrue(any(v.get('parameters')==list(owner) for v in shown['segments']))

    def test_radian_display_is_one_exact_signed_pi_multiple(self):
        sources=('precalculus/train/118','precalculus/train/139','precalculus/train/305','precalculus/train/729','precalculus/test/91','precalculus/test/209')
        for source in sources:
            template=get_template(source);parts=bind_source(template)
            fields=[p for p in parts if not isinstance(p,str)]
            self.assertEqual(len(fields),1,source)
            field=fields[0]
            self.assertEqual(field.symbolic_math,r'\frac{\text{pi\_twelfths}\pi}{12}')
            for n in template.parameters['pi_twelfths']['choices']:
                p={'pi_twelfths':n};text=field.fill(p)
                self.assertEqual(''.join(v if isinstance(v,str) else v.fill(p) for v in parts),template.render(p))
                sign=-1 if text.startswith('-') else 1;text=text.removeprefix('-')
                if text=='0':multiple=Fraction(0)
                else:
                    fraction=re.fullmatch(r'\\frac\{(\d*)\\pi\}\{(\d+)\}',text)
                    if fraction:multiple=Fraction(int(fraction[1] or '1'),int(fraction[2]))
                    else:multiple=Fraction(int(re.fullmatch(r'(\d*)\\pi',text)[1] or '1'))
                self.assertEqual(sign*multiple,Fraction(n,12))

    def test_row_signs_multiply_complete_matrix_entries(self):
        source='precalculus/train/28';template=get_template(source);parts=bind_source(template)
        bare=''.join(v if isinstance(v,str) else (v.symbolic_math or v.label()) for v in parts)
        self.assertIn(r'\text{row\_signs}_{1}\cos\alpha\cos\beta',bare)
        self.assertIn(r'-\text{row\_signs}_{2}\sin\beta',bare)
        self.assertNotRegex(bare,r'when |omitted |≠')
        for signs in product((-1,1),repeat=3):
            p={'row_signs':list(signs)}
            text=''.join(v if isinstance(v,str) else v.fill(p) for v in parts)
            self.assertEqual(text,template.render(p))
            rows=text.split(r'\begin{vmatrix}',1)[1].split(r'\end{vmatrix}',1)[0].split(r'\\')
            bases=((r'\cos\alpha\cos\beta',r'\cos\alpha\sin\beta',r'-\sin\alpha'),(r'-\sin\beta',r'\cos\beta','0'),(r'\sin\alpha\cos\beta',r'\sin\alpha\sin\beta',r'\cos\alpha'))
            for row,sign,base in zip(rows,signs,bases):
                for actual,value in zip(row.split(' & '),base):
                    expected=value if sign>0 or value=='0' else (value[1:] if value.startswith('-') else '-'+value)
                    self.assertEqual(actual,expected)
