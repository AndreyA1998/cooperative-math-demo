"""Independently interpret native polynomials; renderer helpers are not formulas."""
import ast
from fractions import Fraction
import re
import unittest
from support import ensure_runtime
ensure_runtime()
from math_demo.presentation import atomic_presentation
from template_dataset.registry import get_template, generate

CASES = {
 'intermediate_algebra/train/130': (r'\text{coefficient}\,x^{\text{power}}+\text{constant}',),
 'intermediate_algebra/test/865': (r'x^{\text{power}}',r'\sum_{i=0}^{\text{terms}-1}(-1)^i x^{2i}'),
 'intermediate_algebra/train/957': (r'\sum_{i=0}^{\text{terms}-1}x^{i\,\text{stride}}',r'\sum_{i=0}^{\text{terms}-1}x^i'),
 'intermediate_algebra/test/119': (r'\text{coefficients}_{1}+\sum_{i=1}^{3}\text{coefficients}_{i+1}x^{\text{terms}\,\text{multipliers}_{i}}',r'\sum_{i=0}^{\text{terms}-1}x^i'),
 'intermediate_algebra/train/891': (r'x^{\text{power\_a}}-\text{shift}',r'x^{\text{power\_b}}-\text{shift}'),
}

def evaluate_polynomial(source,x):
    source=re.sub(r'x\^\{([0-9]+)\}',r'x**\1',source)
    source=re.sub(r'x\^([0-9]+)',r'x**\1',source)
    source=re.sub(r'(?<=[0-9])x','*x',source).replace(')(',')*(').strip()
    def visit(node):
        if isinstance(node,ast.Constant) and type(node.value) is int:return Fraction(node.value)
        if isinstance(node,ast.Name) and node.id=='x':return Fraction(x)
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            return visit(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        if isinstance(node,ast.BinOp):
            a,b=visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Add):return a+b
            if isinstance(node.op,ast.Sub):return a-b
            if isinstance(node.op,ast.Mult):return a*b
            if isinstance(node.op,ast.Pow) and b.denominator==1 and 0<=b<=2000:return a**int(b)
        raise AssertionError('Unexpected polynomial notation '+ast.dump(node))
    return visit(ast.parse(source,mode='eval').body)

def expected_pair(source,p,x):
    if source.endswith('train/130'):return p['coefficient']*x**p['power']+p['constant'],(x**p['degree']+1)*(x+1)
    if source.endswith('test/865'):return x**p['power'],sum((-1)**i*x**(2*i) for i in range(p['terms']))
    if source.endswith('train/957'):return sum(x**(i*p['stride']) for i in range(p['terms'])),sum(x**i for i in range(p['terms']))
    if source.endswith('test/119'):return p['coefficients'][0]+sum(p['coefficients'][i+1]*x**(p['terms']*m) for i,m in enumerate(p['multipliers'])),sum(x**i for i in range(p['terms']))
    return (x**p['power_a']-p['shift'])*(x**p['power_b']-p['shift']),x*x+x+1

class SparsePolynomialDisplayTests(unittest.TestCase):
    def test_bare_polynomials_show_source_operations_and_index_order(self):
        for source,formulas in CASES.items():
            with self.subTest(source=source):
                presentation=atomic_presentation(source)
                bare=''.join(part.get('symbolic_math',part['text']) for part in presentation['segments'])
                for formula in formulas:self.assertIn(formula,bare)
                self.assertNotRegex(bare,r'(?:_tex_polynomial|expression|join|dividend|divisor)\(')

    def test_filled_polynomials_match_independent_sum_product_interpretations(self):
        for source in CASES:
            template=get_template(source)
            for params in (template.original,*(generate(source,seed)['parameters'] for seed in (0,17,2**64-1))):
                with self.subTest(source=source,params=params):
                    native=template.render(params)
                    filled=''.join(part['text'] for part in atomic_presentation(source,params)['segments'])
                    self.assertEqual(filled,native)
                    dividend,divisor=re.findall(r'\$(.*?)\$',filled)
                    for x in (-2,2,3):
                        self.assertEqual((evaluate_polynomial(dividend,x),evaluate_polynomial(divisor,x)),expected_pair(source,params,x))

    def test_shifted_quintic_uses_the_fifth_ascending_coefficient(self):
        source='intermediate_algebra/test/652';template=get_template(source)
        bare=''.join(part.get('symbolic_math',part['text']) for part in atomic_presentation(source)['segments'])
        self.assertIn(r'\frac{\text{coefficients}_{5}}{5}',bare)
        self.assertNotRegex(bare,r'(?:_tex_polynomial|binomial_shape|expression|join)\(')
        for params in (template.original,*(generate(source,seed)['parameters'] for seed in (0,17,2**64-1))):
            filled=''.join(part['text'] for part in atomic_presentation(source,params)['segments'])
            self.assertEqual(filled,template.render(params))
            h=Fraction(params['coefficients'][4],5)
            self.assertEqual(h.denominator,1)
            # The displayed final factor and excluded root must use exactly h.
            pieces=re.findall(r'\$(.*?)\$',filled)
            factor=pieces[-1].removeprefix('(').removesuffix(')^4')
            for x in (-2,2,3):self.assertEqual(evaluate_polynomial(factor,x),x+h)
            self.assertEqual(pieces[1],r'x\ne'+str(-h))
