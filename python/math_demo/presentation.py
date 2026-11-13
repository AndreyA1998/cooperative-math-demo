"""Read-only, exact display annotations for the composite browser demo.

No markup is stored in schemas or model prompts. All filled fragments must
reconstruct the native question byte-for-byte before being sent to the browser.
"""
import json
import re
from fractions import Fraction

from mathgen.registry import get_template
from mathgen.composite.patterns import (
    _Field, _SourceField, _Fragment, _get_pattern, _json, _conditions, _case_pattern,
)
from mathgen.composite.rendering import _render_inputs
from mathgen.composite.runtime import instantiate
from mathgen.composite.schema import validate_schema


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
    question reconstruction is still asserted in _question for each filled leaf.
    """
    bottom = None if instance is None else instance['bottom_parameters']
    by_id = {node['node_id']: node for node in schema['nodes']}
    nodes = []
    for node in sorted(schema['nodes'], key=lambda item: item['number']):
        external = not node['children']
        params = bottom[node['node_id']] if external and bottom is not None else None
        segments, notes, scope = _question(node, params)
        rules, rule_notes = ([], []) if external else _adapter_math(node, by_id)
        inputs = [{'name': name, 'key': node['label'] + '.' + name, 'role': 'external',
                   'text': None if params is None else _json(params[name])}
                  for name in node['profile']['parameter_names']] if external else []
        nodes.append({'node_id': node['node_id'], 'label': node['label'], 'number': node['number'],
                      'source_id': node['source_id'], 'kind': 'bottom' if external else 'internal',
                      'inputs': inputs, 'segments': segments, 'notes': notes + rule_notes,
                      'adapter': '' if external else _render_inputs(node, by_id),
                      'adapter_math': rules, 'scope': scope})
    return {'version': 'composite-presentation-1', 'mode': 'template' if bottom is None else 'instance',
            'introduction': ['Solve the subproblems in order. R1, R2, … denote their exact answers.',
                             'If a subproblem requests digits without a base subscript, read that digit sequence as a decimal integer in the conversion rules.'],
            'nodes': nodes, 'conclusion': 'Return only ' + by_id[schema['root_id']]['label'] + ', the answer to the final subproblem.'}
