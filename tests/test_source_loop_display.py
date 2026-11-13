"""Display-only loops expose formulas and data organization, not helper calls."""
import re
import unittest
from support import ensure_runtime
ensure_runtime()
from math_demo.presentation import atomic_presentation
from template_dataset.registry import get_template,generate


def shown(source,params=None):
    return ''.join(part.get('symbolic_math',part['text']) if params is None else part['text']
                   for part in atomic_presentation(source,params)['segments'])

class SourceLoopDisplayTests(unittest.TestCase):
    def test_bivariate_quadratic_keeps_zero_terms_in_bare_formula(self):
        source='intermediate_algebra/train/208';template=get_template(source)
        bare=shown(source)
        self.assertIn(r'\text{xx}x^2+\text{xy}xy+\text{yy}y^2+\text{x}x+\text{y}y+\text{offset}',bare)
        self.assertNotRegex(bare,r'(?:expression|join|pieces)\(')
        for p in (template.original,*(generate(source,s)['parameters'] for s in (0,17,2**64-1))):
            text=shown(source,p);self.assertEqual(text,template.render(p))
            polynomial=re.findall(r'\$(.*?)\$',text)[0]
            # Independently parse each signed monomial in the printed polynomial.
            terms=re.findall(r'([+-]?)(\d*)(x\^2|xy|y\^2|x|y)?',polynomial)
            terms=[(sign,int(number or ('1' if monomial else '0')),monomial) for sign,number,monomial in terms if sign or number or monomial]
            for x,y in ((-2,3),(2,-3),(0,0)):
                values={'x^2':x*x,'xy':x*y,'y^2':y*y,'x':x,'y':y,'':1}
                actual=sum((-1 if sign=='-' else 1)*c*values[m] for sign,c,m in terms)
                expected=p['xx']*x*x+p['xy']*x*y+p['yy']*y*y+p['x']*x+p['y']*y+p['offset']
                self.assertEqual(actual,expected)

    def test_iteration_count_is_function_composition(self):
        source='intermediate_algebra/train/487';template=get_template(source)
        bare=shown(source)
        self.assertIn(r'f\circ f\circ\cdots\circ f',bare)
        self.assertIn(r'\text{iterations}',bare)
        self.assertIn(r'\left(k\right)',bare)
        self.assertNotRegex(bare,r'(?:expression|join)\(')
        for count in range(2,9):
            p=dict(template.original,iterations=count)
            text=shown(source,p);self.assertEqual(text,template.render(p))
            self.assertIn('f('*count+'k'+')'*count,text)

    def test_stem_leaf_rule_preserves_grouping_order_and_multiplicity(self):
        source='prealgebra/train/978';template=get_template(source)
        bare=shown(source)
        for fragment in (r'\lfloor',r'\bmod 10',r'\operatorname{sort}',r'\text{scores}',r'\operatorname{length}'):
            self.assertIn(fragment,bare)
        self.assertNotRegex(bare,r'(?:expression|join|setdefault|divmod)\(')
        for part in atomic_presentation(source)['segments']:
            if part.get('symbolic_math'):
                self.assertNotIn(r'\\',part['symbolic_math'], 'Math renderer forbids alignment breaks inside a symbolic field')
        samples=(template.original,dict(maximum=110,scores=[100,0,19,19,19,90,101]),
                 *(generate(source,s)['parameters'] for s in (0,17,2**64-1)))
        for p in samples:
            text=shown(source,p);self.assertEqual(text,template.render(p))
            body=text.split(r'\begin{array}{r|l}',1)[1].split(r'\end{array}',1)[0]
            scores=[];stems=[]
            for row in body.split(r'\\'):
                stem,leaves=row.split('&');stem=int(stem);stems.append(stem)
                digits=[int(value) for value in leaves.split(r'\;')]
                self.assertEqual(digits,sorted(digits));self.assertTrue(all(0<=d<10 for d in digits))
                scores.extend(10*stem+digit for digit in digits)
            self.assertEqual(stems,sorted(set(stems)))
            self.assertEqual(scores,sorted(p['scores']))

    def test_conjugate_root_fields_keep_sign_and_position(self):
        for source in ('intermediate_algebra/train/300','intermediate_algebra/train/765','intermediate_algebra/test/649'):
            template=get_template(source);bare=shown(source)
            length=template.parameters['radicands']['min_length']
            for i in range(1,length+1):
                self.assertIn(r'\text{centers}_{%d}+\text{radical\_coefficients}_{%d}\sqrt{\text{radicands}_{%d}}'%(i,i,i),bare)
            self.assertNotRegex(bare,r'when |omitted |abs\(|expression\(')
            for p in (template.original,*(generate(source,s)['parameters'] for s in (0,17,2**64-1))):
                text=shown(source,p);self.assertEqual(text,template.render(p))
                roots=re.findall(r'\$(.*?)\$',text)[0].split(r',\; ')
                for i,root in enumerate(roots):
                    if i>=length:self.assertEqual(int(root),p['centers'][i]);continue
                    prefix,radicand=root.split(r'\sqrt{')
                    match=re.fullmatch(r'(?:(-?\d+)([+-]))?(-?\d*)',prefix)
                    self.assertIsNotNone(match)
                    center,sign,scale=match.groups()
                    a=int(center) if center is not None else 0
                    b=int(scale) if scale not in ('','-') else (-1 if scale=='-' else 1)
                    if sign=='-':b=-b
                    d=int(radicand.removesuffix('}'))
                    self.assertEqual((a,b,d),(p['centers'][i],p['radical_coefficients'][i],p['radicands'][i]))

    def test_cubic_keeps_its_symbolic_zero_branch_separate(self):
        from test_sparse_polynomial_display import evaluate_polynomial
        source='precalculus/train/434';template=get_template(source);bare=shown(source)
        self.assertIn('quadratic_coefficient = linear_coefficient = constant_coefficient = 0',bare)
        self.assertIn('x^3+px+q=0',bare)
        self.assertIn(r'+\text{quadratic\_coefficient}x^2+\text{linear\_coefficient}x+\text{constant\_coefficient}',bare)
        self.assertNotRegex(bare,r'formula\(|expression\(|omitted ')
        self.assertEqual(shown(source,template.original),template.render(template.original))
        for p in (dict(quadratic_coefficient=2,linear_coefficient=0,constant_coefficient=-7),
                  dict(quadratic_coefficient=0,linear_coefficient=-1,constant_coefficient=0),
                  *(generate(source,s)['parameters'] for s in (0,17,2**64-1))):
            text=shown(source,p);self.assertEqual(text,template.render(p))
            polynomial=re.findall(r'\$(.*?)\$',text)[1].removesuffix('=0')
            if not any(p.values()):self.assertEqual(polynomial,'x^3+px+q');continue
            for x in (-2,2,3):
                self.assertEqual(evaluate_polynomial(polynomial,x),x**3+p['quadratic_coefficient']*x*x+p['linear_coefficient']*x+p['constant_coefficient'])
