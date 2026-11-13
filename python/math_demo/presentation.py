"""Read-only, exact display annotations for atomic and composite browser tasks.

No markup is stored in schemas or model prompts. All filled fragments must
reconstruct the native question byte-for-byte before being sent to the browser.
"""
import json
import re
import operator
from dataclasses import dataclass
from functools import lru_cache
from inspect import getclosurevars
from types import SimpleNamespace, FunctionType, CodeType
from fractions import Fraction

from template_dataset.registry import get_template
from composite_dataset.patterns import (
    _Field, _SourceField, _Fragment, _get_pattern, _json, _conditions, _case_pattern,
    _source_parts, _proxy_parts, _Slot, _MARKER,
)
from composite_dataset.rendering import _render_inputs
from composite_dataset.runtime import instantiate
from composite_dataset.schema import validate_schema
from composite_dataset.smart_adapters import evaluate_adapter


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


def _operator_math(operator, label):
    ref = r'\mathrm{R}_{' + label[1:] + '}'
    kind = operator['kind']
    if kind == 'identity':
        return ref, []
    if kind == 'affine':
        return r'\left(' + _number(operator['scale']) + r'\right)' + ref + r'+\left(' + _number(operator['offset']) + r'\right)', []
    classifier = operator['classifier']
    zero, one = operator['target_domain']['values']
    notes = []
    if classifier['kind'] == 'threshold':
        less = classifier['less_bit']
        first, second = (zero, one) if less == 0 else (one, zero)
        condition = ref + '<' + _number(classifier['cut'])
    else:
        spec = classifier['spec']
        sub = label[1:]
        n, d = 'N_{' + sub + '}', 'D_{' + sub + '}'
        numerator = r'\left(' + str(spec['numerator']) + r'\right)' + n
        numerator += r'+\left(' + str(spec['denominator']) + r'\right)' + d
        quotient = r'\left\lfloor\frac{' + numerator + '}{' + str(spec['divisor']) + r'}\right\rfloor'
        condition = r'\operatorname{mod}\left(' + quotient + ',' + str(spec['modulus']) + r'\right)<' + str(spec['threshold'])
        first, second = zero, one
        notes.append('$' + ref + '=' + r'\frac{' + n + '}{' + d + '}$ in lowest terms, with $' + d + '>0$.')
    return (r'\begin{cases}' + _number(first) + r' & ' + condition + r'\\' + _number(second) + r' & \text{otherwise}\end{cases}', notes)


def _adapter_math(node, by_id):
    names, rows = node['profile']['parameter_names'], node['profile']['rows']
    used = set(names)
    def local(prefix, index):
        label = prefix + str(index + 1)
        while label in used:
            label = '_' + label
        used.add(label)
        return label
    signals = [local('u', i) for i in range(len(names))]
    rules, notes = [], []
    for binding in node['bindings']:
        expression, definitions = _operator_math(binding['operator'], by_id[binding['source_node']]['label'])
        rules.append(_tex_text(signals[binding['input_index']]) + ' = ' + expression)
        notes.extend(definitions)
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
            values = [_tex_text(_json(rows[index][name])) for name in parameters]
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
    pattern = _get_pattern(node['source_id'], _json(node['profile']['rows']))
    # Certified diffs can split TeX syntax across substitutions. Display those
    # as complete native cases; inserting boxes or placeholders would change
    # grouping or remove delimiters. The saved pattern and model text stay intact.
    if pattern.scope != 'certified-cases' and any(
            _structural_tex(text)
            for part in pattern.parts if isinstance(part, _Fragment)
            for _, text in part.alternatives):
        rows = node['profile']['rows']
        template = get_template(node['source_id'])
        pattern = _case_pattern(rows, tuple(template.render(row) for row in rows),
                                node['profile']['parameter_names'])
    role = 'external' if not node['children'] else 'internal'
    prefix = node['label']
    notes, segments = [], []
    if pattern.scope == 'certified-cases':
        fragment = pattern.parts[0]
        if params is None:
            text = '\n\n'.join('If ' + _conditions(fragment.names, values) + ': ' + statement
                                 for values, statement in fragment.alternatives)
            notes.append('Use the statement matching the input values.')
        else:
            text = fragment.fill(params)
        segments = [{'kind': 'text', 'text': text}]
    else:
        fragments = {}
        for part in pattern.parts:
            if isinstance(part, str):
                segments.append({'kind': 'text', 'text': part})
                continue
            if isinstance(part, (_Field, _SourceField)):
                name, dependencies = part.label(), [part.name]
                if isinstance(part, _Field):
                    notes.extend(rule for rule in part.legend() if rule not in notes)
            elif isinstance(part, _Fragment):
                if part not in fragments:
                    fragments[part] = 'fragment ' + str(len(fragments) + 1)
                    if params is None:
                        choices = '; '.join(_conditions(part.names, values) + ' → ' + _json(text)
                                            for values, text in part.alternatives)
                        notes.append('Insert ' + fragments[part] + ' using the matching inputs: ' + choices + '.')
                name, dependencies = fragments[part], list(part.names)
            else:
                raise TypeError('Unknown certified pattern part')
            segments.append({'kind': 'parameter', 'text': part.fill(params) if params is not None else (prefix + '.' + name if role == 'external' else name),
                             'name': name, 'key': prefix + '.' + name, 'role': role,
                             'filled': params is not None, 'parameters': dependencies})
    if params is not None:
        native = get_template(node['source_id']).render(params)
        if ''.join(part['text'] for part in segments) != native:
            raise ValueError('Display annotations do not reconstruct the native question')
    return segments, notes, pattern.scope


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
                   'text': None if params is None else _json(params[name])}
                  for name in node['profile']['parameter_names']]
        incoming = []
        for binding in node['bindings']:
            source = binding['source_node']
            answer = None if instance is None else trace[source]['answer']
            incoming.append({'source_node': source, 'source_label': by_id[source]['label'],
                             'input_index': binding['input_index'],
                             'input_name': node['profile']['parameter_names'][binding['input_index']],
                             'answer': answer,
                             'value': None if answer is None else _json(evaluate_adapter(binding['operator'], answer))})
        nodes.append({'node_id': node['node_id'], 'label': node['label'], 'number': node['number'],
                      'source_id': node['source_id'], 'kind': 'bottom' if external else 'internal',
                      'inputs': inputs, 'segments': segments, 'notes': notes + rule_notes,
                      'answer': None if row is None else row['answer'], 'incoming': incoming,
                      'adapter': '' if external else _render_inputs(node, by_id),
                      'adapter_math': rules, 'scope': scope})
    return {'version': 'composite-presentation-2', 'mode': 'template' if instance is None else 'instance',
            'introduction': ['Solve the subproblems in order. R1, R2, … denote their exact answers.',
                             'If a subproblem requests digits without a base subscript, read that digit sequence as a decimal integer in the conversion rules.'],
            'nodes': nodes, 'conclusion': 'Return only ' + by_id[schema['root_id']]['label'] + ', the answer to the final subproblem.'}


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
        for name in _referenced_names(original.__code__):
            value = namespace.get(name)
            if value is Fraction:
                namespace[name] = _lift_call(Fraction, record, symbolic_constant=True)
            elif isinstance(value, FunctionType) and value.__module__.startswith('template_dataset.families'):
                namespace[name] = _lift_call(value, record, tex=True) if value.__name__ in _TEX_FORMATTERS else clone(value)
        closure = None if original.__closure__ is None else tuple(cell(clone(c.cell_contents)) for c in original.__closure__)
        result = FunctionType(original.__code__, namespace, original.__name__, original.__defaults__, closure)
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
    if name == ('template_dataset.families.algebra_v2', '_derived.<locals>.render'):
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
    if name == ('template_dataset.families.extensions.algebra_equations', '_build_bound_equation.<locals>.render'):
        context = getclosurevars(render).nonlocals
        proxy = SimpleNamespace(render=context['bindings'].render, parameters=template.parameters, original=template.original)
        parts = _source_parts(proxy)
        if context['adapted']:
            return tuple(part.replace('Find the real roots of', 'Find the unique real root of').replace('Enter the roots, separated by commas.', '') if isinstance(part, str) else part for part in parts)
        return parts
    return ()


@lru_cache(maxsize=None)
def _atomic_parts(source_id):
    template = get_template(source_id)
    rewrites = _has_text_rewrite(template.render)
    builders = [_source_parts, _derived_source_parts]
    if not rewrites:
        builders.extend((_proxy_parts, _expression_parts, lambda t: _expression_parts(t, lifted=True)))
    for build in builders:
        try:
            parts = build(template)
            if parts and ''.join(p if isinstance(p, str) else p.fill(template.original) for p in parts) == template.render(template.original):
                return parts
        except (ArithmeticError, AttributeError, IndexError, KeyError, TypeError, ValueError):
            pass
    return ()


def atomic_presentation(source_id, params=None):
    """Annotate an ordinary atomic domain without limiting it to binary profiles.

    The fallback explicitly owns the whole computed statement. It never guesses
    parameter positions from equal digits, sampled diffs, or substring matches.
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
            names = [part.name] if isinstance(part, (_Field, _SourceField)) else list(part.names)
            if isinstance(part, _Field):
                notes.extend(note for note in part.legend() if note not in notes)
            segments.append({'kind': 'parameter', 'name': name, 'key': name,
                             'text': name if params is None else part.fill(params),
                             'role': 'external', 'filled': params is not None, 'parameters': names})
    else:
        names = list(template.parameters)
        label = 'statement(' + ', '.join(names) + ')'
        segments = [{'kind': 'parameter', 'name': label, 'key': 'statement', 'text': label if params is None else template.render(params),
                     'role': 'external', 'filled': params is not None, 'parameters': names}]
        notes.append('Форма условия вычисляется из параметров; после заполнения появится точный текст задачи.')
    return {'version': 'atomic-presentation-1', 'mode': 'template' if params is None else 'instance',
            'source_id': source_id, 'scope': scope, 'segments': segments, 'notes': notes,
            'inputs': [{'name': name, 'key': name, 'role': 'external', 'domain': domain,
                        'text': None if params is None else _json(params[name]), 'domain_display': _json(domain)}
                       for name, domain in template.parameters.items()]}
