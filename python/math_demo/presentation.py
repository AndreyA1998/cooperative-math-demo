"""Read-only, exact display annotations for atomic and composite browser tasks.

No markup is stored in schemas or model prompts. All filled fragments must
reconstruct the native question byte-for-byte before being sent to the browser.
"""
import ast
import json
import textwrap
import re
import operator
from dataclasses import dataclass
from functools import lru_cache
from inspect import getclosurevars, getsource
from types import SimpleNamespace, FunctionType, CodeType
from fractions import Fraction

from template_dataset.registry import get_template
from .expression_patterns import source_expression_parts
from .source_bindings import bind_source
from composite_dataset.patterns import (
    _Field, _SourceField, _Fragment, _get_pattern, _json, _conditions, _case_pattern,
    _source_parts, _proxy_parts, _Slot, _MARKER,
)
from composite_dataset.rendering import _render_inputs
from composite_dataset.runtime import instantiate
from composite_dataset.schema import validate_schema
from composite_dataset.smart_adapters import evaluate_adapter


def _display_value(value):
    """Readable exact chip text; serialization stays at the JSON boundary."""
    return value if isinstance(value, str) else _json(value)


def _tex_text(value):
    escapes = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}',
               '_': r'\_', '%': r'\%', '#': r'\#', '&': r'\&',
               '$': r'\$', '^': r'\textasciicircum{}', '~': r'\textasciitilde{}'}
    return r'\text{' + ''.join(escapes.get(c, c) for c in str(value)) + '}'


def _number(value):
    fraction = Fraction(str(value))
    if fraction.denominator == 1:
        return str(fraction.numerator)
    sign = '-' if fraction < 0 else ''
    return sign + r'\frac{' + str(abs(fraction.numerator)) + '}{' + str(fraction.denominator) + '}'


def _linear_math(terms, offset=0):
    """Render an exact linear expression without zero terms or unit factors."""
    pieces = []
    for coefficient, symbol in (*terms, (offset, '')):
        coefficient = Fraction(str(coefficient))
        if not coefficient:
            continue
        sign = '-' if coefficient < 0 else ('+' if pieces else '')
        magnitude = abs(coefficient)
        factor = '' if symbol and magnitude == 1 else _number(magnitude)
        pieces.append(sign + factor + symbol)
    return ''.join(pieces) or '0'


def _operator_math(operator, label):
    ref = r'\operatorname{Ans}(' + label[1:] + ')'
    kind = operator['kind']
    if kind == 'identity':
        return ref, []
    if kind == 'affine':
        return _linear_math(((operator['scale'], ref),), operator['offset']), []
    classifier = operator['classifier']
    zero, one = operator['target_domain']['values']
    notes = []
    if classifier['kind'] == 'threshold':
        less = classifier['less_bit']
        first, second = (zero, one) if less == 0 else (one, zero)
        condition = ref + '<' + _number(classifier['cut'])
    else:
        spec = classifier['spec']
        n = r'\text{числитель}\left(' + ref + r'\right)'
        d = r'\text{знаменатель}\left(' + ref + r'\right)'
        numerator = _linear_math(((spec['numerator'], n), (spec['denominator'], d)))
        quotient = numerator if spec['divisor'] == 1 else r'\left\lfloor\frac{' + numerator + '}{' + str(spec['divisor']) + r'}\right\rfloor'
        if spec['divisor'] != 1:
            notes.append(r'$\lfloor x\rfloor$ — округление вниз до ближайшего целого.')
        condition = r'\operatorname{mod}\left(' + quotient + ',' + str(spec['modulus']) + r'\right)<' + str(spec['threshold'])
        first, second = zero, one
        notes.append('Числитель и знаменатель берутся у сокращённой дроби с положительным знаменателем.')
        notes.append('mod(a, m) — неотрицательный остаток от деления a на m: от 0 до m−1.')
    return (r'\begin{cases}' + _number(first) + r' & ' + condition + r'\\' + _number(second) + r' & \text{otherwise}\end{cases}', notes)


def _local_adapter_names(names):
    """One namespace for formulas and edge annotations, including collisions."""
    used = set(names)
    def local(prefix, index):
        label = prefix + str(index + 1)
        while label in used:
            label = '_' + label
        used.add(label)
        return label
    return [local('u', i) for i in range(len(names))], local


def _adapter_math(node, by_id):
    names, rows = node['profile']['parameter_names'], node['profile']['rows']
    signals, local = _local_adapter_names(names)
    rules, notes = [], []
    for binding in node['bindings']:
        expression, definitions = _operator_math(binding['operator'], by_id[binding['source_node']]['label'])
        rules.append(_tex_text(signals[binding['input_index']]) + ' = ' + expression)
        notes.extend(note for note in definitions if note not in notes)
    for axis, ports in enumerate(node['adapter']['groups']):
        bit = signals[ports[0]]
        if len(ports) > 1:
            bit = local('b', axis)
            rules.append(_tex_text(bit) + r'=\left(' + '+'.join(_tex_text(signals[p]) for p in ports) + r'\right)\bmod 2')
        parameters = [names[p] for p in ports]
        lhs = ', '.join(_tex_text(p) for p in parameters)
        if len(parameters) > 1:
            lhs = r'\left(' + lhs + r'\right)'
        choices = []
        for index in (0, 1 << axis):
            values = [_tex_text(_display_value(rows[index][name])) for name in parameters]
            choices.append(values[0] if len(values) == 1 else r'\left(' + ', '.join(values) + r'\right)')
        rules.append(lhs + r'=\begin{cases}' + choices[0] + ' & ' + _tex_text(bit) + r'=0\\' + choices[1] + r' & \text{otherwise}\end{cases}')
    return rules, notes


def _structural_tex(text):
    """A substitution may not own a delimiter or cross a TeX group boundary."""
    braces = fences = 0
    for token in re.findall(r'\\(?:[A-Za-z]+|.)|[{}$]', text):
        if token in ('$', r'\(', r'\)', r'\[', r'\]', r'\begin', r'\end'):
            return True
        if token == '{':
            braces += 1
        elif token == '}':
            braces -= 1
        elif token == r'\left':
            fences += 1
        elif token == r'\right':
            fences -= 1
        if braces < 0 or fences < 0:
            return True
    return bool(braces or fences)


def _question(node, params):
    """Use the ordinary native field owners for both tree and atomic cards."""
    result = atomic_presentation(node['source_id'], params)
    role = 'external' if not node['children'] else 'internal'
    prefix = node['label']
    segments = []
    for original in result['segments']:
        part = dict(original)
        if part['kind'] == 'parameter':
            part['key'] = prefix + '.' + part['key']
            part['role'] = role
        segments.append(part)
    return segments, result['notes'], result['scope']


def presentation(schema, seed=None):
    """Build annotations from a validated schema and optional exact seed."""
    if seed is None:
        validate_schema(schema)
        return _presentation_validated(schema)
    instance = instantiate(schema, seed)
    return _presentation_validated(schema, instance)


def _presentation_validated(schema, instance=None):
    """Annotate a schema and an optional instance produced by strict runtime.

    Private callers must already have validated the schema. When supplied, the
    instance must be the result of instantiating that exact schema. Native
    question reconstruction is still asserted in _question for every filled node.
    """
    trace = {} if instance is None else {row['node_id']: row for row in instance['trace']}
    by_id = {node['node_id']: node for node in schema['nodes']}
    nodes = []
    for node in sorted(schema['nodes'], key=lambda item: item['number']):
        external = not node['children']
        role = 'external' if external else 'internal'
        row = trace.get(node['node_id'])
        params = None if row is None else row['parameters']
        segments, notes, scope = _question(node, params)
        rules, rule_notes = ([], []) if external else _adapter_math(node, by_id)
        inputs = [{'name': name, 'key': node['label'] + '.' + name, 'role': role,
                   'text': None if params is None else _display_value(params[name])}
                  for name in node['profile']['parameter_names']]
        incoming = []
        signals, _ = _local_adapter_names(node['profile']['parameter_names'])
        for binding in node['bindings']:
            source = binding['source_node']
            answer = None if instance is None else trace[source]['answer']
            incoming.append({'source_node': source, 'source_label': by_id[source]['label'],
                             'input_index': binding['input_index'],
                             'signal_name': signals[binding['input_index']],
                             'input_name': node['profile']['parameter_names'][binding['input_index']],
                             'answer': answer,
                             'value': None if answer is None else _display_value(evaluate_adapter(binding['operator'], answer))})
        nodes.append({'node_id': node['node_id'], 'label': node['label'], 'number': node['number'],
                      'source_id': node['source_id'], 'kind': 'bottom' if external else 'internal',
                      'inputs': inputs, 'segments': segments, 'notes': notes + rule_notes,
                      'question_notes': notes, 'adapter_notes': rule_notes,
                      'answer': None if row is None else row['answer'], 'incoming': incoming,
                      'adapter': '' if external else _render_inputs(
                          node, by_id, **({'text_version': schema['text_version']} if 'text_version' in schema else {})),
                      'adapter_math': rules, 'scope': scope})
    return {'version': 'composite-presentation-2', 'mode': 'template' if instance is None else 'instance',
            'introduction': ['Solve the numbered subproblems in order. Use each answer in the rules referring to that subproblem.',
                             'If a subproblem requests digits without a base subscript, read that digit sequence as a decimal integer in the conversion rules.'],
            'nodes': nodes, 'conclusion': 'Return only the answer to subproblem ' + str(by_id[schema['root_id']]['number']) + '.'}


@dataclass(frozen=True)
class _ExpressionField:
    expression: object
    spec: str = ''
    conversion: str = ''

    def fill(self, params):
        value = self.expression.value(params)
        if self.conversion == 'str':
            return str(value)
        if self.conversion == 'repr':
            return repr(value)
        if self.conversion == 'percent':
            return self.spec % value
        return format(value, self.spec)

    def label(self):
        return self.expression.label

    @property
    def names(self):
        return self.expression.names


class _Expression(_Slot):
    """Capture arithmetic and formatting, refusing branching or coercion.

    Native Python operators evaluate the expression again when filling a slot.
    Nothing is inferred from the digits of a rendered statement.
    """
    def __init__(self, label, names, value, record, length=None):
        self.label, self.names, self.value = label, names, value
        self.record, self.length = record, length

    def __format__(self, spec):
        # Check format support on an ordinary value before recording it.
        if not re.fullmatch(r'[+ -]?\d{0,3},?(?:\.\d{1,2})?[dsf]?', spec):
            raise ValueError('Unsupported expression format')
        return self.record(_ExpressionField(self, spec))

    def __str__(self):
        return self.record(_ExpressionField(self, conversion='str'))

    def __repr__(self):
        return self.record(_ExpressionField(self, conversion='repr'))

    def __getitem__(self, index):
        if self.length is None or type(index) is not int:
            raise ValueError('Unsupported expression index')
        if not -self.length <= index < self.length:
            raise IndexError(index)
        return _Expression(self.label + '[' + str(index + 1) + ']', self.names,
                           lambda p: self.value(p)[index], self.record)

    def binary(self, other, symbol, operation, reverse=False):
        if not isinstance(other, _Expression):
            if type(other) not in (int, float, str):
                raise ValueError('Unsupported expression constant')
            constant = other
            other = _Expression(repr(constant), (), lambda p: constant, self.record)
        a, b = (other, self) if reverse else (self, other)
        names = tuple(dict.fromkeys((*a.names, *b.names)))
        return _Expression('(' + a.label + symbol + b.label + ')', names,
                           lambda p: operation(a.value(p), b.value(p)), self.record)

    def unary(self, label, operation):
        return _Expression(label + '(' + self.label + ')', self.names,
                           lambda p: operation(self.value(p)), self.record)

    def __add__(self, x): return self.binary(x, '+', operator.add)
    def __radd__(self, x): return self.binary(x, '+', operator.add, True)
    def __sub__(self, x): return self.binary(x, '-', operator.sub)
    def __rsub__(self, x): return self.binary(x, '-', operator.sub, True)
    def __mul__(self, x): return self.binary(x, '*', operator.mul)
    def __rmul__(self, x): return self.binary(x, '*', operator.mul, True)
    def __truediv__(self, x): return self.binary(x, '/', operator.truediv)
    def __rtruediv__(self, x): return self.binary(x, '/', operator.truediv, True)
    def __floordiv__(self, x): return self.binary(x, '//', operator.floordiv)
    def __rfloordiv__(self, x): return self.binary(x, '//', operator.floordiv, True)
    def __mod__(self, x): return self.binary(x, '%', operator.mod)
    def __rmod__(self, x): return self.binary(x, '%', operator.mod, True)
    def __pow__(self, x): return self.binary(x, '**', operator.pow)
    def __rpow__(self, x): return self.binary(x, '**', operator.pow, True)
    def __neg__(self): return self.unary('-', operator.neg)
    def __pos__(self): return self.unary('+', operator.pos)
    def __abs__(self): return self.unary('abs', abs)


def _expression_parts(template, lifted=False):
    fields = []
    def record(field):
        fields.append(field)
        return '\ue000' + str(len(fields) - 1) + '\ue001'
    slots = {}
    for name, domain in template.parameters.items():
        length = domain.get('min_length') if domain.get('min_length') == domain.get('max_length') else None
        slots[name] = _Expression(name, (name,), lambda p, key=name: p[key], record, length)
    render = _lift_renderer(template.render, record) if lifted else template.render
    text = render(slots)
    pieces = _MARKER.split(text)
    parts = tuple(piece if i % 2 == 0 else fields[int(piece)] for i, piece in enumerate(pieces))
    return parts if fields else ()


# These native helpers return a complete mathematical fragment. Treating their
# output as one slot preserves signs, rational reductions, and zero terms.
_TEX_FORMATTERS = {'_tex', '_tex_polynomial'}


def _walk_expressions(value):
    if isinstance(value, _Expression):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_expressions(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_expressions(item)


def _resolve_expressions(value, params):
    if isinstance(value, _Expression):
        return value.value(params)
    if isinstance(value, (list, tuple)):
        return type(value)(_resolve_expressions(item, params) for item in value)
    if isinstance(value, dict):
        return {key: _resolve_expressions(item, params) for key, item in value.items()}
    return value


def _lift_call(function, record, *, tex=False, symbolic_constant=False):
    def call(*args, **kwargs):
        expressions = tuple(_walk_expressions((args, kwargs)))
        if not expressions and not symbolic_constant:
            return function(*args, **kwargs)
        names = tuple(dict.fromkeys(name for expression in expressions for name in expression.names))
        if tex and not names:
            return function(*_resolve_expressions(args, {}), **_resolve_expressions(kwargs, {}))
        label = function.__name__.strip('_') + '(' + ', '.join(names) + ')'
        value = lambda p: function(*_resolve_expressions(args, p), **_resolve_expressions(kwargs, p))
        expression = _Expression(label, names, value, record)
        return record(_ExpressionField(expression)) if tex else expression
    return call


def _referenced_names(code):
    names = set(code.co_names)
    for value in code.co_consts:
        if isinstance(value, CodeType):
            names.update(_referenced_names(value))
    return names


_PERCENT_FIELD = re.compile(r'%(?:\(([^)]+)\))?([#0\- +]*\d*(?:\.\d+)?[hlL]?[diouxXeEfFgGcrsa%])')


def _percent_format(left, right, record):
    """Trace native %-format fields, leaving numeric modulo unchanged."""
    if not isinstance(left, str) or not tuple(_walk_expressions(right)):
        return left % right
    values = right if isinstance(right, tuple) else (right,)
    parts, offset, index = [], 0, 0
    for match in _PERCENT_FIELD.finditer(left):
        literal = left[offset:match.start()]
        if '%' in literal:
            raise ValueError('Unsupported symbolic percent format')
        parts.append(literal)
        key, format_tail = match.groups()
        if format_tail == '%':
            parts.append('%')
        else:
            value = right[key] if key is not None else values[index]
            if key is None:
                index += 1
            spec = '%' + format_tail
            if isinstance(value, _Expression) and value.names:
                parts.append(record(_ExpressionField(value, spec, 'percent')))
            else:
                parts.append(spec % _resolve_expressions(value, {}))
        offset = match.end()
    if '%' in left[offset:]:
        raise ValueError('Unsupported symbolic percent format')
    parts.append(left[offset:])
    if not isinstance(right, dict) and index != len(values):
        raise ValueError('Unused symbolic percent format argument')
    return ''.join(parts)


@lru_cache(maxsize=None)
def _percent_code(original):
    """Rewrite only the display clone of a native named function.

    The original function, its mathematical operations and its globals are not
    edited. Source unavailable or ambiguous means no rewrite and a safe fallback.
    Compiling an enclosing scope preserves the exact native free-variable names.
    """
    try:
        source = ast.parse(textwrap.dedent(getsource(original)))
        if len(source.body) != 1 or not isinstance(source.body[0], ast.FunctionDef):
            return original.__code__
        definition = source.body[0]
        if definition.name != original.__name__ or not any(isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) for node in ast.walk(definition)):
            return original.__code__
        helper = '_math_demo_percent_format'
        if helper in _referenced_names(original.__code__):
            return original.__code__
        class RewritePercent(ast.NodeTransformer):
            def visit_BinOp(self, node):
                self.generic_visit(node)
                if isinstance(node.op, ast.Mod):
                    return ast.copy_location(ast.Call(ast.Name(helper, ast.Load()), [node.left, node.right], []), node)
                return node
        definition = RewritePercent().visit(definition)
        definition.decorator_list = []
        assignments = [ast.Assign([ast.Name(name, ast.Store())], ast.Constant(None))
                       for name in original.__code__.co_freevars]
        wrapper = ast.FunctionDef(name='_display_scope',
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=[*assignments, definition], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
        compiled = compile(module, original.__code__.co_filename, 'exec')
        outer = next(value for value in compiled.co_consts if isinstance(value, CodeType))
        code = next(value for value in outer.co_consts if isinstance(value, CodeType) and value.co_name == original.__name__)
        return code if set(code.co_freevars) == set(original.__code__.co_freevars) else original.__code__
    except (OSError, TypeError, SyntaxError, ValueError, StopIteration):
        return original.__code__


def _lift_renderer(function, record):
    """Clone the renderer graph; native solvers and module globals stay intact."""
    active, done = set(), {}
    def cell(value):
        return (lambda: value).__closure__[0]
    def clone(original):
        if not isinstance(original, FunctionType) or not original.__module__.startswith('template_dataset.families'):
            return original
        if original in done:
            return done[original]
        if original in active:
            raise ValueError('Recursive symbolic helper')
        active.add(original)
        namespace = dict(original.__globals__)
        namespace['_math_demo_percent_format'] = lambda left, right: _percent_format(left, right, record)
        for name in _referenced_names(original.__code__):
            value = namespace.get(name)
            if value is Fraction:
                namespace[name] = _lift_call(Fraction, record, symbolic_constant=True)
            elif isinstance(value, FunctionType) and value.__module__.startswith('template_dataset.families'):
                namespace[name] = _lift_call(value, record, tex=True) if value.__name__ in _TEX_FORMATTERS else clone(value)
        code = _percent_code(original)
        enclosed = dict(zip(original.__code__.co_freevars, original.__closure__ or ()))
        closure = tuple(cell(clone(enclosed[name].cell_contents)) for name in code.co_freevars) if code.co_freevars else None
        result = FunctionType(code, namespace, original.__name__, original.__defaults__, closure)
        result.__kwdefaults__ = original.__kwdefaults__
        done[original] = result
        active.remove(original)
        return result
    return clone(function)


def _has_text_rewrite(function, seen=None):
    """Marker strings cannot safely model post-format substitutions like '+-'."""
    if not isinstance(function, FunctionType) or not function.__module__.startswith('template_dataset.families'):
        return False
    seen = set() if seen is None else seen
    if function in seen:
        return False
    seen.add(function)
    if 'replace' in _referenced_names(function.__code__):
        return True
    enclosed = () if function.__closure__ is None else (cell.cell_contents for cell in function.__closure__)
    referenced = (function.__globals__.get(name) for name in _referenced_names(function.__code__))
    return any(_has_text_rewrite(value, seen) for value in (*enclosed, *referenced))


@dataclass(frozen=True)
class _DerivedSourceField:
    context: object
    index: int
    raw: str
    exponent: bool
    names: tuple
    description: str

    def fill(self, params):
        value = self.context['display'](*self.context['args'](params))[self.index]
        if value == int(self.raw.replace(',', '')):
            return self.raw
        text = format(value, ',') if ',' in self.raw else str(value)
        return '{' + text + '}' if self.exponent and len(text) > 1 else text

    def label(self):
        return self.description


def _derived_source_parts(template):
    """Reuse explicit native source spans, including their derived expressions."""
    render = template.render
    name = getattr(render, '__module__', ''), getattr(render, '__qualname__', '')
    if name == ('template_dataset.families.algebra.symbolic_forms', '_derived.<locals>.render'):
        context = getclosurevars(render).nonlocals
        problem, parts, offset = context['problem'], [], 0
        descriptions = None
        try:
            slots = {key: _Expression(key, (key,), lambda p, k=key: p[k], lambda x: '') for key in template.parameters}
            descriptions = context['display'](*context['args'](slots))
        except (ArithmeticError, AttributeError, IndexError, KeyError, TypeError, ValueError):
            pass
        for index, match in enumerate(context['spans']):
            start, end = match.span()
            symbolic = descriptions[index] if descriptions is not None else None
            names = symbolic.names if isinstance(symbolic, _Expression) else tuple(template.parameters)
            label = symbolic.label if isinstance(symbolic, _Expression) else 'expression ' + str(index + 1)
            field = _DerivedSourceField(context, index, match[0], problem[:start].rstrip().endswith(('^', '_')), names, label)
            parts.extend((problem[offset:start], field))
            offset = end
        return (*parts, problem[offset:])
    if name == ('template_dataset.families.algebra.real_roots', '_build_bound_equation.<locals>.render'):
        context = getclosurevars(render).nonlocals
        proxy = SimpleNamespace(render=context['bindings'].render, parameters=template.parameters, original=template.original)
        parts = _source_parts(proxy)
        if context['adapted']:
            return tuple(part.replace('Find the real roots of', 'Find the unique real root of').replace('Enter the roots, separated by commas.', '') if isinstance(part, str) else part for part in parts)
        return parts
    return ()


@dataclass(frozen=True)
class _GroupedField:
    parts: tuple
    names: tuple
    description: str

    def fill(self, params):
        return ''.join(part if isinstance(part, str) else part.fill(params) for part in self.parts)

    def label(self):
        return self.description


def _decimal_parts(parts, template):
    """Group the two native digit fields of a declared scaled numeric input."""
    result, index = [], 0
    while index < len(parts):
        part = parts[index]
        names = (part.name,) if isinstance(part, (_Field, _SourceField)) else getattr(part, 'names', ())
        if len(names) == 1 and index + 2 < len(parts) and parts[index + 1] == '.':
            following = parts[index + 2]
            other = (following.name,) if isinstance(following, (_Field, _SourceField)) else getattr(following, 'names', ())
            unit = template.parameters[names[0]].get('unit')
            if names == other and unit and Fraction(unit).denominator > 1:
                result.append(_GroupedField(tuple(parts[index:index + 3]), names,
                                            names[0] + '/' + str(Fraction(unit).denominator)))
                index += 3
                continue
        result.append(part)
        index += 1
    return tuple(result)


@lru_cache(maxsize=None)
def _atomic_parts(source_id):
    template = get_template(source_id)
    rewrites = _has_text_rewrite(template.render)
    builders = [_source_parts, _derived_source_parts, bind_source]
    if not rewrites:
        builders.extend((_proxy_parts, _expression_parts, lambda t: _expression_parts(t, lifted=True)))
    builders.append(source_expression_parts)
    for build in builders:
        try:
            parts = _decimal_parts(build(template), template)
            if parts and not any(_structural_tex(p.fill(template.original)) for p in parts if not isinstance(p, str) and not getattr(p, 'conditional_literal', False)) and ''.join(p if isinstance(p, str) else p.fill(template.original) for p in parts) == template.render(template.original):
                return parts
        except (ArithmeticError, AttributeError, IndexError, KeyError, TypeError, ValueError):
            pass
    return ()


def atomic_presentation(source_id, params=None):
    """Annotate an ordinary atomic domain without limiting it to binary profiles.

    A fallback statement is plain text, with separately named input chips.
    Unknown ownership never becomes a whole-statement parameter annotation.
    """
    template = get_template(source_id)
    parts = _atomic_parts(source_id)
    notes, segments = [], []
    if params is not None and parts:
        try:
            if ''.join(p if isinstance(p, str) else p.fill(params) for p in parts) != template.render(params):
                parts = ()
        except (ArithmeticError, AttributeError, IndexError, KeyError, TypeError, ValueError):
            parts = ()
    scope = 'native-fields' if parts else 'computed-statement'
    if parts:
        for part in parts:
            if isinstance(part, str):
                segments.append({'kind': 'text', 'text': part})
                continue
            name = part.label()
            if getattr(part, 'conditional_literal', False):
                segments.append({'kind': 'text', 'text': name if params is None else part.fill(params),
                                 'parameters': list(part.names), 'control': part.control})
                continue
            names = [part.name] if isinstance(part, (_Field, _SourceField)) else list(part.names)
            if isinstance(part, _Field):
                notes.extend(note for note in part.legend() if note not in notes)
            segments.append({'kind': 'parameter', 'name': name, 'key': name,
                             'text': name if params is None else part.fill(params),
                             'role': 'external', 'filled': params is not None, 'parameters': names})
            symbolic_math = getattr(part, 'symbolic_math', None)
            if params is None and symbolic_math and not _structural_tex(symbolic_math):
                segments[-1]['symbolic_math'] = symbolic_math
    else:
        names = list(template.parameters)
        label = 'statement(' + ', '.join(names) + ')'
        segments = [{'kind': 'text', 'text': label if params is None else template.render(params)}]
        notes.append('Форма условия вычисляется из параметров; после заполнения появится точный текст задачи.')
    return {'version': 'atomic-presentation-1', 'mode': 'template' if params is None else 'instance',
            'source_id': source_id, 'scope': scope, 'segments': segments, 'notes': notes,
            'inputs': [{'name': name, 'key': name, 'role': 'external', 'domain': domain,
                        'text': None if params is None else _display_value(params[name]), 'domain_display': _json(domain)}
                       for name, domain in template.parameters.items()]}
