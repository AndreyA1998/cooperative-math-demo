"""Independent arithmetic readers for all three adapter representations.

The readers below consume the printed rules. They never inspect an operator AST
or call a native classifier to obtain their arithmetic decisions.
"""
import ast
from fractions import Fraction
from itertools import product
import json
import re
import unittest

from support import ensure_runtime
ensure_runtime()
from composite_dataset import build_schema, instantiate
from composite_dataset.rendering import _render_inputs
from composite_dataset.smart_adapters import describe_adapter, evaluate_adapter
from math_demo.presentation import _adapter_math, _operator_math


def arithmetic(source, environment):
    """Interpret only exact arithmetic in the observed display grammar."""
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return Fraction(node.value)
        if isinstance(node, ast.Name):
            return Fraction(environment[node.id])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right
            if isinstance(node.op, ast.Mod):
                # Explicit Euclidean remainder; no native adapter helper.
                return left - (left // right) * right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            args = [visit(argument) for argument in node.args]
            if node.func.id == 'floor' and len(args) == 1:
                return Fraction(args[0].numerator // args[0].denominator)
            if node.func.id == 'mod' and len(args) == 2:
                return args[0] - (args[0] // args[1]) * args[1]
        raise AssertionError('Unexpected displayed arithmetic: ' + ast.dump(node))
    return visit(ast.parse(source.strip(), mode='eval').body)


def plain_value(expression, environment):
    if ' if ' not in expression:
        return arithmetic(expression, environment)
    first, condition = expression.split(' if ', 1)
    condition, second = condition.split('; otherwise ', 1)
    annotation = re.search(r' \((R\d+)=n/d reduced, d>0; mod is nonnegative\)$', second)
    local = dict(environment)
    if annotation:
        q = Fraction(local[annotation[1]])
        local.update(n=q.numerator, d=q.denominator)
        second = second[:annotation.start()]
    left, right = condition.split(' < ', 1)
    if ' mod ' in left:
        quotient, modulus = left.rsplit(' mod ', 1)
        left = '(' + quotient + ') % ' + modulus
    return json.loads(first if arithmetic(left, local) < arithmetic(right, local) else second)


def tex_arithmetic(source):
    source = re.sub(r'\\text\{числитель\}\\left\(\\text\{выход №(\d+)\}\\right\)', r'n\1', source)
    source = re.sub(r'\\text\{знаменатель\}\\left\(\\text\{выход №(\d+)\}\\right\)', r'd\1', source)
    source = re.sub(r'\\text\{выход №(\d+)\}', r'R\1', source)

    def group(start):
        if source[start] != '{': raise AssertionError(source)
        depth = 1
        for end in range(start + 1, len(source)):
            depth += (source[end] == '{') - (source[end] == '}')
            if not depth: return source[start + 1:end], end + 1
        raise AssertionError('Unclosed displayed fraction')

    while r'\frac{' in source:
        start = source.rfind(r'\frac{')
        numerator, middle = group(start + len(r'\frac'))
        denominator, end = group(middle)
        source = source[:start] + '((' + numerator + ')/(' + denominator + '))' + source[end:]
    source = source.replace(r'\left\lfloor', 'floor(').replace(r'\right\rfloor', ')')
    source = source.replace(r'\operatorname{mod}', 'mod')
    source = source.replace(r'\left', '').replace(r'\right', '').replace(r'\bmod', '%')
    source = re.sub(r'\\text\{([^{}]*)\}', lambda m: m[1].replace(r'\_', '_'), source)
    return re.sub(r'(?<=[0-9)])(?=[Rnd][0-9])', '*', source)


def pretty_value(expression, environment):
    local = dict(environment)
    for name, value in environment.items():
        if re.fullmatch(r'R\d+', name):
            q = Fraction(value)
            local['n' + name[1:]], local['d' + name[1:]] = q.numerator, q.denominator
    branches = re.fullmatch(r'\\begin\{cases\}(.*?) & (.*?)\\\\(.*?) & \\text\{otherwise\}\\end\{cases\}', expression)
    if not branches:
        return arithmetic(tex_arithmetic(expression), local)
    first, condition, second = branches.groups()
    left, right = condition.split('<')
    branch = first if arithmetic(tex_arithmetic(left), local) < arithmetic(tex_arithmetic(right), local) else second
    return arithmetic(tex_arithmetic(branch), local)


def parameter_value(text):
    """Read the emitted JSON scalar/list or a tuple of such values."""
    return ast.literal_eval(text.strip())


def plain_rules(text, answers):
    environment = dict(answers)
    for line in text.splitlines():
        left, right = line.split(' = ', 1)
        if ', otherwise ' in right:
            first, rest = right.split(' if ', 1)
            condition, second = rest.split(', otherwise ', 1)
            signal, zero = condition.split(' = ')
            value = parameter_value(first if environment[signal] == int(zero) else second)
        elif ' mod ' in right and ' if ' not in right:
            left_expr, divisor = right.rsplit(' mod ', 1)
            value = arithmetic('(' + left_expr + ') % ' + divisor, environment)
        else:
            value = plain_value(right, environment)
        if left.startswith('('):
            names = [name.strip() for name in left[1:-1].split(',')]
            environment.update(zip(names, value))
        else:
            environment[left] = value
    return environment


def pretty_rules(rules, answers, parameter_types):
    environment = dict(answers)
    for rule in rules:
        left, right = rule.split('=', 1)
        left = tex_arithmetic(left).strip()
        branches = re.fullmatch(r'\\begin\{cases\}(.*?) & \\text\{([^{}]*)\}=0\\\\(.*?) & \\text\{otherwise\}\\end\{cases\}', right)
        if branches:
            first, signal, second = branches.groups()
            branch = first if environment[signal.replace(r'\_', '_')] == 0 else second
            names = [name.strip() for name in left.strip('()').split(',')]
            tokens = re.findall(r'\\text\{([^{}]*)\}', branch)
            if len(tokens) != len(names):
                raise AssertionError('One displayed value is required for every target parameter')
            # Presentation removes JSON string quotes. Parameter types are still
            # declared by the schema: read string glyphs exactly, including 0011.
            # This uses only type information, never the row's expected values.
            values = [token.replace(r'\_', '_') if parameter_types[name] is str
                      else parameter_value(token) for name, token in zip(names, tokens)]
            value = tuple(values) if left.startswith('(') else values[0]
        elif r'\bmod' in right:
            value = arithmetic(tex_arithmetic(right), environment)
        else:
            value = pretty_value(right.strip(), environment)
        if left.startswith('('):
            environment.update(zip((name.strip() for name in left[1:-1].split(',')), value))
        else:
            environment[left] = value
    return environment


class AdapterConsistencyTests(unittest.TestCase):
    def assert_representations(self, op, answers):
        plain = describe_adapter(op, 'R37')
        pretty, _ = _operator_math(op, 'R37')
        for answer in answers:
            with self.subTest(operator=op, answer=answer):
                expected = evaluate_adapter(op, answer)
                expected = Fraction(expected) if isinstance(expected, (int, str)) else expected
                self.assertEqual(plain_value(plain, {'R37': answer}), expected)
                self.assertEqual(pretty_value(pretty, {'R37': answer}), expected)

    def test_identity_and_affine_exact_rational_and_large_values(self):
        for values, result_type in (([-1, 1], 'int'), (['-3/2', '7/4'], 'rational_string')):
            op = {'kind': 'identity', 'result_type': result_type,
                  'source_domain': {'kind': 'finite', 'values': [str(x) for x in values]},
                  'target_domain': {'kind': 'finite', 'values': values}}
            self.assert_representations(op, values)
        for scale, offset in (('1', '0'), ('-1', '0'), ('-1', '9007199254740993'),
                              ('-1/3', '9007199254740993/7'), ('11/7', '-19/3')):
            answers = [str(Fraction(q)) for q in ('-13/5', '9007199254740995/11')]
            targets = [str(Fraction(scale)*Fraction(q)+Fraction(offset)) for q in answers]
            op = {'kind': 'affine', 'result_type': 'rational_string', 'scale': scale, 'offset': offset,
                  'source_domain': {'kind': 'finite', 'values': answers},
                  'target_domain': {'kind': 'finite', 'values': targets}}
            self.assert_representations(op, answers)
            with self.assertRaises(ValueError): evaluate_adapter(op, '0')

    def test_threshold_equality_and_both_orientations(self):
        for cut, less_bit in product(('0', '-3/2', '9007199254740993/7'), (0, 1)):
            op = {'kind': 'select', 'source_domain': {'kind': 'rational'},
                  'target_domain': {'kind': 'finite', 'values': [11, 29]},
                  'classifier': {'kind': 'threshold', 'cut': cut, 'less_bit': less_bit}}
            q = Fraction(cut)
            self.assert_representations(op, (q-1, q, q+1))
            # Strict '<' means equality must choose the opposite branch.
            self.assertEqual(evaluate_adapter(op, q), [11, 29][1-less_bit])

    def test_floor_mod_signed_reduced_values_unit_coefficients_and_divisors(self):
        answers = ('0', '-1', '-13/5', '8/4', Fraction(6, -4), Fraction(-6, -4), '9007199254740993/17')
        for a, b, divisor in product((-7, -1, 0, 1, 11), (-1, 0, 1), (1, 2, 7)):
            op = {'kind': 'select', 'source_domain': {'kind': 'rational'},
                  'target_domain': {'kind': 'finite', 'values': [0, 1]},
                  'classifier': {'kind': 'floor_mod', 'spec': {
                      'op': 'floor_mod', 'numerator': a, 'denominator': b,
                      'divisor': divisor, 'modulus': 5, 'threshold': 2}}}
            self.assert_representations(op, answers)
        # A negative quotient must floor, and the remainder must be nonnegative:
        # floor(-3/4)=-1; -1 = (-1)*5 + 4, so the >=2 branch is selected.
        op['classifier']['spec'].update(numerator=1, denominator=0, divisor=4)
        self.assertEqual(evaluate_adapter(op, '-3'), 1)
        pretty, notes = _operator_math(op, 'R37')
        self.assertEqual(pretty_value(pretty, {'R37': '-3'}), 1)
        self.assertIn('неотрицательный', ' '.join(notes))
        self.assertIn('сокращённой дроби', ' '.join(notes))
        self.assertIn('положительным знаменателем', ' '.join(notes))

    def test_grouped_parity_joint_maps_from_both_printed_rule_sets(self):
        wide = 9007199254740993
        rows = [
            {'u1': wide, 'b1': '2/3', 'rate': [1, 2]},
            {'u1': wide + 2, 'b1': '2/3', 'rate': [3, 4]},
            {'u1': wide, 'b1': '-5/7', 'rate': [1, 2]},
            {'u1': wide + 2, 'b1': '-5/7', 'rate': [3, 4]},
        ]
        identity = {'kind': 'identity', 'result_type': 'int',
                    'source_domain': {'kind': 'finite', 'values': ['0', '1']},
                    'target_domain': {'kind': 'finite', 'values': [0, 1]}}
        node = {'profile': {'parameter_names': ['u1', 'b1', 'rate'], 'rows': rows},
                'adapter': {'groups': [[0, 2], [1]]},
                'bindings': [{'input_index': i, 'source_node': str(i), 'operator': identity} for i in range(3)]}
        by_id = {str(i): {'label': 'R' + str(i+1)} for i in range(3)}
        plain, (pretty, _) = _render_inputs(node, by_id), _adapter_math(node, by_id)
        for first, second, third in product((0, 1), repeat=3):
            # Independent reading: the first/third signals select together by
            # odd parity; the second signal selects only the rational string.
            expected = {'u1': wide + (2 if first != third else 0),
                        'rate': [3, 4] if first != third else [1, 2],
                        'b1': '-5/7' if second else '2/3'}
            answers = dict(R1=first, R2=second, R3=third)
            for decoded in (plain_rules(plain, answers), pretty_rules(pretty, answers, {name: type(value) for name, value in rows[0].items()})):
                self.assertEqual({name: decoded[name] for name in expected}, expected)

    def test_scalar_strings_are_unquoted_and_preserve_words_decimals_and_leading_zeros(self):
        from copy import deepcopy
        pairs = [('fraction', '2/3', '-5/7'), ('word', 'north west', 'south east'),
                 ('digits', '0011', '0100'), ('decimal', '0.050', '2.500'),
                 ('sequence', [1, 2], [3, 4])]
        for name, zero, one in pairs:
            node = {'profile': {'parameter_names': [name], 'rows': [{name: zero}, {name: one}]},
                    'adapter': {'groups': [[0]]},
                    'bindings': [{'input_index': 0, 'source_node': 'child', 'operator': {'kind': 'identity'}}]}
            original = deepcopy(node)
            rules, _ = _adapter_math(node, {'child': {'label': 'R1'}})
            self.assertEqual(node, original)
            for bit, expected in ((0, zero), (1, one)):
                self.assertEqual(pretty_rules(rules, {'R1': bit}, {name: type(zero)})[name], expected)
                if isinstance(expected, str):
                    self.assertIn(r'\text{' + expected + '}', rules[-1])
                    self.assertNotIn(r'\text{"' + expected + '"}', rules[-1])
            if isinstance(zero, list):
                self.assertIn(r'\text{[1,2]}', rules[-1])

    def test_real_tree_plain_and_pretty_rules_and_answer_free_canonical_download(self):
        for depth, width, seed in ((2, 3, 112), (3, 5, 42), (4, 6, 2**64-1)):
            schema = build_schema(depth, width, seed)
            by_id = {node['node_id']: node for node in schema['nodes']}
            originals = split_subproblems(schema['problem_template'])
            instances = [instantiate(schema, variant) for variant in (0, 17)]
            for instance in instances:
                text = instance['problem']
                sections = split_subproblems(text)
                trace = {row['node_id']: row for row in instance['trace']}
                for node in schema['nodes']:
                    section = sections[node['number']]
                    if node['children']:
                        # Every upper rule and condition stays symbolic across
                        # filled variants. Only bottom conditions are instantiated.
                        self.assertEqual(section, originals[node['number']])
                        plain = _render_inputs(node, by_id)
                        pretty, _ = _adapter_math(node, by_id)
                        self.assertIn(plain, section)
                        answers = {by_id[binding['source_node']]['label']: trace[binding['source_node']]['answer']
                                   for binding in node['bindings']}
                        for decoded in (plain_rules(plain, answers), pretty_rules(pretty, answers, {name: type(value) for name, value in node['profile']['rows'][0].items()})):
                            self.assertEqual({name: decoded[name] for name in node['profile']['parameter_names']},
                                             trace[node['node_id']]['parameters'])
                    else:
                        from template_dataset.registry import get_template
                        native = get_template(node['source_id']).render(instance['bottom_parameters'][node['node_id']])
                        self.assertEqual(section.strip(), native)
                    self.assertNotIn(node['source_id'], text)
                self.assertNotIn('parameters_text', text)
                self.assertNotIn('"trace"', text)
                self.assertNotIn('{{', text)


def split_subproblems(text):
    parts = re.split(r'\nSubproblem (\d+) \(R\d+\)\n\n', text)
    result = {int(parts[i]): parts[i+1].rstrip() for i in range(1, len(parts), 2)}
    last = max(result)
    result[last] = result[last].split('\n\n\nReturn only ', 1)[0].rstrip()
    return result
