"""Display the source spans and argument bindings declared by native renderers.

These adapters read rendering metadata only. They never call a solver, infer
ownership from matching digits, or change a native function or its globals.
"""
import ast
from dataclasses import dataclass
from inspect import getclosurevars, signature
import re


_PREFIX = 'template_dataset.families.'


@dataclass(frozen=True)
class NativeDisplayBinding:
    """The native display callable and its exact public argument order."""

    function: object
    names: tuple

    def arguments(self, parameters):
        return tuple(parameters[name] for name in self.names)


@dataclass(frozen=True)
class SourceBindingField:
    """One expression inside an explicitly declared native source span."""

    expression: object
    description: str

    @property
    def names(self):
        return self.expression.names

    def label(self):
        return self.description

    @property
    def symbolic_math(self):
        return getattr(self.expression, 'math', None)

    def fill(self, parameters):
        return str(self.expression.get(parameters))


@dataclass(frozen=True)
class SourceLiteralField:
    """A native numeric token, including its declared display scale."""

    name: str
    decimal_places: int = 0
    exponent: bool = False

    @property
    def names(self):
        return (self.name,)

    def label(self):
        return self.name if not self.decimal_places else f'{self.name}/{10 ** self.decimal_places}'

    def fill(self, parameters):
        number = str(parameters[self.name])
        if self.decimal_places:
            number = number.zfill(self.decimal_places + 1)
            number = number[:-self.decimal_places] + '.' + number[-self.decimal_places:]
        if self.exponent and len(number) > 1:
            number = '{' + number + '}'
        return number


def _literal_parts(template, context, identity):
    """Use authoritative literal offsets rather than searching rendered digits."""
    source = context['problem']
    if identity[0] == _PREFIX + 'algebra.equations_and_expressions':
        spans = [(start, end, SourceLiteralField(name, places))
                 for start, end, name, places in sorted(context['parameters'].spans)]
    else:
        spans = [(token.start(), token.end(), SourceLiteralField(
                    name, exponent=bool(token.start() and source[token.start()-1] == '^')))
                 for token, name in zip(context['tokens'], context['fields']) if name != '_']
    if {field.name for _, _, field in spans} != set(template.parameters):
        raise ValueError('Literal source bindings do not match the public parameters')
    parts, offset = [], 0
    for start, end, field in spans:
        if not 0 <= offset <= start < end <= len(source):
            raise ValueError('Invalid native literal span')
        parts.extend((source[offset:start], field))
        offset = end
    parts.append(source[offset:])
    return tuple(parts)


def native_display_binding(template):
    """Unwrap known argument adapters without executing their statement code.

    The wrapper's captured key order is authoritative: alphabetical parameter
    order or a solver's signature could silently swap independent givens.
    """
    render = template.render
    identity = getattr(render, '__module__', ''), getattr(render, '__qualname__', '')
    if identity == (_PREFIX + 'algebra.parameter_bindings',
                    'register.<locals>.factory.<locals>.unpack.<locals>.<lambda>'):
        context = getclosurevars(render).nonlocals
        binding = NativeDisplayBinding(context['function'], tuple(context['names']))
    elif identity == (_PREFIX + 'algebra.given_bindings',
                      'register.<locals>.unpack.<locals>.<lambda>'):
        context = getclosurevars(render).nonlocals
        binding = NativeDisplayBinding(context['fn'], tuple(context['original']))
    elif identity == (_PREFIX + 'word_problems.decimal_arithmetic', 'add.<locals>.<lambda>'):
        context = getclosurevars(render).nonlocals
        if not callable(context.get('statement')):
            return None
        names = getclosurevars(context['unpack']).nonlocals['names']
        binding = NativeDisplayBinding(context['statement'], tuple(names))
    else:
        return None
    if len(binding.names) != len(set(binding.names)) or set(binding.names) != set(template.parameters):
        raise ValueError('Native display argument bindings do not match the public parameters')
    return binding


def _description(expression):
    """Keep the expression already resolved to public parameter names."""
    return expression.description


def _balanced_fragment(text):
    depth = fences = 0
    for token in re.findall(r'\\(?:[A-Za-z]+|.)|[{}$&]', text):
        if token in ('$', '&', r'\(', r'\)', r'\[', r'\]', r'\begin', r'\end'):
            return False
        if token == '{': depth += 1
        elif token == '}': depth -= 1
        elif token == r'\left': fences += 1
        elif token == r'\right': fences -= 1
        if depth < 0 or fences < 0: return False
    return depth == fences == 0


def _inside_math(source, start, end):
    # Explicit source spans may be inside a formula without including its fences.
    if re.search(r'(?<!\\)\$|\\[()\[\]]', source[start:end]):
        return False
    if len(re.findall(r'(?<!\\)\$', source[:start])) % 2:
        return True
    for opening, closing in ((r'\(', r'\)'), (r'\[', r'\]')):
        if source.rfind(opening, 0, start) > source.rfind(closing, 0, start):
            return closing not in source[start:end]
    return False


def _polynomial_parts(template, identity):
    """Expose the operations declared by two native polynomial constructors.

    Sparse powers are expanded into a dense coefficient buffer by the native
    display code. That buffer is a formatting implementation detail; the source
    dividend/divisor declarations supply the mathematical formulas below. Each
    evaluator and every literal still comes from the original display AST.
    """
    module = _PREFIX + 'algebra.polynomial_operations'
    formulas = None
    if identity == (module, '_modular_remainder.<locals>.render'):
        geometric = r'\sum_{i=0}^{\text{terms}-1}x^i'
        # These are the five declared input contracts of _modular_remainder;
        # serialized family IDs and corpus numbers are not presentation rules.
        contracts = {
            frozenset(('degree', 'power', 'coefficient', 'constant')): {
                frozenset(('power', 'coefficient', 'constant')):
                    r'\text{coefficient}\,x^{\text{power}}+\text{constant}',
            },
            frozenset(('terms', 'power')): {
                frozenset(('power',)): r'x^{\text{power}}',
                frozenset(('terms',)): r'\sum_{i=0}^{\text{terms}-1}(-1)^i x^{2i}',
            },
            frozenset(('terms', 'stride')): {
                frozenset(('terms', 'stride')): r'\sum_{i=0}^{\text{terms}-1}x^{i\,\text{stride}}',
                frozenset(('terms',)): geometric,
            },
            frozenset(('terms', 'multipliers', 'coefficients')): {
                frozenset(('terms', 'multipliers', 'coefficients')):
                    r'\text{coefficients}_{1}+\sum_{i=1}^{3}\text{coefficients}_{i+1}x^{\text{terms}\,\text{multipliers}_{i}}',
                frozenset(('terms',)): geometric,
            },
            frozenset(('power_a', 'power_b', 'shift')): {
                frozenset(('power_a', 'shift')): r'x^{\text{power\_a}}-\text{shift}',
                frozenset(('power_b', 'shift')): r'x^{\text{power\_b}}-\text{shift}',
            },
        }
        formulas = contracts.get(frozenset(template.parameters))
        if formulas is None:
            return ()
    elif identity == (_PREFIX + 'intermediate_algebra.callable_bindings',
                      'bind.<locals>.unpack.<locals>.<lambda>'):
        function = getclosurevars(template.render).nonlocals['function']
        if (function.__module__ != _PREFIX + 'intermediate_algebra.constrained_systems_and_stationary_points'
                or 'binomial_shape' not in function.__code__.co_names
                or set(template.parameters) != {'coefficients', 'rhs'}):
            return ()
    else:
        return ()

    from .expression_patterns import MathValue, source_expression_parts
    result, matched = [], set()
    for part in source_expression_parts(template):
        formula = None
        owners = getattr(part, 'names', ())
        if not isinstance(part, str):
            if formulas is not None and part.label().startswith('_tex_polynomial('):
                key = frozenset(owners)
                formula = formulas.get(key)
                if formula is not None:
                    matched.add(key)
            elif formulas is None:
                # binomial_shape proves the valid quintic has h=c[-2]/5.
                # c stores six ascending coefficients, so h=coefficients[5]/5
                # in the public one-based indexing. rhs constrains validity but
                # does not change this displayed shift or the excluded root.
                shift = r'\frac{\text{coefficients}_{5}}{5}'
                if part.label() == '-binomial_shape(coefficients, rhs)[0]':
                    formula = '-' + shift
                elif part.label() == '_tex_polynomial(coefficients, rhs)':
                    formula = 'x+' + shift
                if formula is not None:
                    owners = ('coefficients',)
                    matched.add(part.label())
        if formula is not None:
            value = MathValue(owners, part.value.evaluate, formula, formula)
            part = SourceBindingField(value, formula)
        result.append(part)
    expected = (set(formulas) if formulas is not None else
                {'-binomial_shape(coefficients, rhs)[0]', '_tex_polynomial(coefficients, rhs)'})
    if matched != expected:
        raise ValueError('Native polynomial display no longer matches its declared source contract')
    return tuple(result)


def _loop_parts(template, identity):
    """Keep native loop output, while stating its actual mathematical rule."""
    field_names = formula = None
    if identity == (_PREFIX + 'algebra.extrema', '_quadratic_form.<locals>.render'):
        field_names = ('xx', 'xy', 'yy', 'x', 'y', 'offset')
        formula = (r'\text{xx}x^2+\text{xy}xy+\text{yy}y^2+'
                   r'\text{x}x+\text{y}y+\text{offset}')
    elif identity == (_PREFIX + 'intermediate_algebra.callable_bindings',
                      'bind.<locals>.unpack.<locals>.<lambda>'):
        function = getclosurevars(template.render).nonlocals['function']
        if (function.__module__, function.__qualname__) == (
                _PREFIX + 'intermediate_algebra.equations_and_elementary_extrema', 'parity_step_prompt'):
            field_names = ('iterations',)
            formula = (r'\underbrace{(f\circ f\circ\cdots\circ f)}_{'
                       r'\text{iterations}\text{ applications}}\left(k\right)')
    elif identity == (_PREFIX + 'word_problems.decimal_arithmetic', 'add.<locals>.<lambda>'):
        binding = native_display_binding(template)
        if binding and (binding.function.__module__, binding.function.__qualname__) == (
                _PREFIX + 'word_problems.finite_counts', 'mode_statement'):
            field_names = ('scores',)
            # The bracketed list retains repeated leaves. Stems and leaves are
            # sorted exactly as the source's sorted(data)/divmod/setdefault loop.
            formula = (r'\text{one row for each distinct }s='
                       r'\lfloor\text{scores}_i/10\rfloor,\ '
                       r'1\le i\le\operatorname{length}(\text{scores}),\ s\text{ increasing}'
                       r';\quad s\mid\operatorname{sort}(['
                       r'\text{scores}_i\bmod 10:1\le i\le\operatorname{length}(\text{scores}),\ '
                       r'\lfloor\text{scores}_i/10\rfloor=s])')
    if field_names is None:
        return ()
    from .expression_patterns import MathValue, source_expression_parts
    result, matched = [], 0
    for part in source_expression_parts(template):
        if not isinstance(part, str) and set(part.names) == set(field_names):
            value = MathValue(part.names, part.value.evaluate, formula, formula)
            part = SourceBindingField(value, formula)
            matched += 1
        result.append(part)
    if matched != 1:
        raise ValueError('Native display loop no longer matches its source field')
    return tuple(result)


def _root_parts(template, identity):
    """Read signed radical roots and the genuinely distinct cubic cases."""
    conjugates = identity == (_PREFIX + 'algebra.polynomial_operations', '_conjugates.<locals>.render')
    cubic = False
    if identity == (_PREFIX + 'arithmetic.finite_integer_and_radical_models',
                    'add.<locals>.unpack.<locals>.<lambda>'):
        function = getclosurevars(template.render).nonlocals['fn']
        cubic = (function.__module__, function.__qualname__) == (
            _PREFIX + 'precalculus.determinants_vectors_and_planes', 'cubic_circulant')
    if not (conjugates or cubic):
        return ()
    from .expression_patterns import ConditionalLiteral, Field, MathValue, source_expression_parts
    parts = source_expression_parts(template)
    names = tuple(template.parameters)
    if conjugates:
        count = template.parameters['radicands']['min_length']
        result, index = [], 0
        for part in parts:
            if not isinstance(part, str) and set(part.names) == set(names):
                index += 1
                formula = (r'\text{centers}_{%d}+\text{radical\_coefficients}_{%d}'
                           r'\sqrt{\text{radicands}_{%d}}') % (index, index, index)
                part = SourceBindingField(MathValue(part.names, part.value.evaluate, formula, formula), formula)
            result.append(part)
        if index != count:
            raise ValueError('Native radical list no longer matches its declared source order')
        return tuple(result)

    # The all-zero parameter encoding intentionally retains symbolic p and q;
    # replacing it by x^3 alone would change the original displayed problem.
    # Show two complete bare branches, while only the selected native branch
    # contributes bytes to the filled condition. Conditional prose is text.
    fields = [i for i, part in enumerate(parts) if not isinstance(part, str)]
    if not fields:
        raise ValueError('Native cubic no longer exposes coefficient fields')
    start, end = fields[0], fields[-1] + 1
    before, after = ''.join(parts[:start]), ''.join(parts[end:])
    middle = parts[start:end]
    native = lambda p: ''.join(part if isinstance(part, str) else part.fill(p) for part in middle)
    zero = lambda p: all(p[name] == 0 for name in names)
    formula = (r'+\text{quadratic\_coefficient}x^2+'
               r'\text{linear\_coefficient}x+\text{constant\_coefficient}')
    result = []
    for selected, header in ((True, 'If quadratic_coefficient = linear_coefficient = constant_coefficient = 0: '),
                             (False, 'Otherwise: ')):
        active = lambda p, branch=selected: zero(p) == branch
        result.append(Field(ConditionalLiteral(names, lambda p: '', header, header)))
        result.append(Field(ConditionalLiteral(names, lambda p, match=active: before if match(p) else '', before, header)))
        evaluate = lambda p, match=active: native(p) if match(p) else ''
        if selected:
            result.append(Field(ConditionalLiteral(names, evaluate, '+px+q', header)))
        else:
            result.append(SourceBindingField(MathValue(names, evaluate, formula, formula), formula))
        result.append(Field(ConditionalLiteral(names, lambda p, match=active: after if match(p) else '', after, header)))
        result.append(Field(ConditionalLiteral(names, lambda p: '', '\n\n', header)))
    return tuple(result)


def _tex_argument_parts(template, identity):
    """Use native TeX argument boundaries, rather than numeric-token boundaries."""
    from .expression_patterns import MathValue, definition, source_expression_parts
    if identity == (_PREFIX + 'algebra.symbolic_forms', '_derived.<locals>.render'):
        context = getclosurevars(template.render).nonlocals
        names = set(template.parameters)
        if names == {'shift', 'denominator'}:
            owners = ('shift', None, ('1', 'denominator'), None)
        elif names == {'x', 'neg_y', 'slope_numerator', 'slope_denominator'}:
            owners = ('x', 'neg_y', ('slope_numerator', 'slope_denominator'))
        else:
            return ()
        source, spans = context['problem'], context['spans']
        if len(spans) != len(owners):
            return ()
        result, offset = [], 0
        def field(name, *, argument=False):
            formula = r'\text{' + name.replace('_', r'\_') + '}'
            if argument:
                formula = '{' + formula + '}'
            return SourceBindingField(MathValue((name,), lambda p, n=name: str(p[n]), name, formula), name)
        for span, owner in zip(spans, owners):
            start, end = span.span()
            result.append(source[offset:start])
            if isinstance(owner, tuple):
                # The source deliberately encodes two one-digit TeX arguments
                # as 10*m+n (or 10+n), guarded by its native joint constraints.
                # Keep the command literal and expose each argument separately.
                if len(span[0]) != 2 or not re.search(r'\\frac\s*$', source[:start]):
                    return ()
                for name in owner:
                    result.append(name if name == '1' else field(name, argument=True))
            elif owner is None:
                result.append(span[0])
            else:
                result.append(field(owner))
            offset = end
        result.append(source[offset:])
        return tuple(result)

    if identity == (_PREFIX + 'geometry.euclidean_and_coordinate_models', '_exact_trig.<locals>.render'):
        context = getclosurevars(template.render).nonlocals
        if not context['radians'] or context['name'] != 'pi_twelfths':
            return ()
        parts = source_expression_parts(template)
        indices = [i for i, part in enumerate(parts) if not isinstance(part, str)]
        start, end = indices[0], indices[-1] + 1
        middle = parts[start:end]
        if any(isinstance(part, str) or part.names != ('pi_twelfths',) for part in middle):
            raise ValueError('Native radian formatter no longer exposes one signed angle')
        formula = r'\frac{\text{pi\_twelfths}\pi}{12}'
        value = MathValue(('pi_twelfths',), lambda p: ''.join(part.fill(p) for part in middle), formula, formula)
        return (*parts[:start], SourceBindingField(value, formula), *parts[end:])

    if identity != (_PREFIX + 'arithmetic.finite_integer_and_radical_models',
                    'add.<locals>.unpack.<locals>.<lambda>'):
        return ()
    function = getclosurevars(template.render).nonlocals['fn']
    if (function.__module__, function.__qualname__) != (
            _PREFIX + 'precalculus.determinants_vectors_and_planes', 'rotations_prompt'):
        return ()
    # The initial native rows are literal mathematical expressions. Each row is
    # multiplied by its declared ±1 sign; zero entries remain constant zero.
    declaration = next(statement.value for statement in definition(function).body
                       if isinstance(statement, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'rows' for target in statement.targets))
    bases = [term for row in ast.literal_eval(declaration) for term in row]
    parts = source_expression_parts(template)
    result, index, at = [], 0, 0
    while at < len(parts):
        part = parts[at]
        if isinstance(part, str):
            result.append(part); at += 1; continue
        if index >= len(bases) or at + 1 >= len(parts) or not isinstance(parts[at+1], str):
            raise ValueError('Native signed matrix no longer exposes its entry boundaries')
        base = bases[index]
        literal = base.lstrip('-')
        if not parts[at+1].startswith(literal):
            raise ValueError('Native signed matrix entry no longer matches its declared monomial')
        if base == '0':
            result.append('0')
        else:
            formula = ('-' if base.startswith('-') else '') + r'\text{row\_signs}_{' + str(index//3+1) + '}' + literal
            value = MathValue(('row_signs',), lambda p, f=part, term=literal: f.fill(p)+term, formula, formula)
            result.append(SourceBindingField(value, formula))
        result.append(parts[at+1][len(literal):])
        index += 1; at += 2
    if index != len(bases):
        raise ValueError('Native signed matrix entry count changed')
    return tuple(result)



def _derived_coefficient_parts(template, identity):
    """Read three native numeric bindings whose formatting masks their formula.

    int() merely spells an already integral linked coefficient; the recurrence
    generator merely spells the first six terms defined in the visible text.
    Native display calls still supply every filled token, including braces and
    comma grouping. No solver participates in either representation.
    """
    if identity != (_PREFIX + 'algebra.symbolic_forms', '_derived.<locals>.render'):
        return ()
    context = getclosurevars(template.render).nonlocals
    names = tuple(template.parameters)
    def symbol(name):
        return r'\text{' + name.replace('_', r'\_') + '}'
    def direct(name):
        return ((name,), symbol(name))
    if names == ('divisor_slope', 'divisor_constant', 'quotient_linear',
                 'quotient_num', 'quotient_den', 'dividend_constant'):
        a, b, c, d, e, k = map(symbol, names)
        rules = [direct(names[0]), None,
                 ((names[0], names[1], names[2]), r'\left(' + a+c+'-'+b+r'\right)'), None,
                 (names[:5], r'\left(' + b+c+r'-\frac{'+a+d+'}{'+e+r'}\right)'),
                 direct(names[5]), direct(names[0]), direct(names[1]), None,
                 direct(names[2]), direct(names[3]), direct(names[4])]
    elif names == ('divisor_slope', 'divisor_constant', 'quotient_lead',
                   'dividend_quadratic', 'ratio_num', 'ratio_den', 'dividend_constant'):
        a, b, m, q, n, d, k = map(symbol, names)
        rules = [((names[0], names[2]), a+m), None, direct(names[3]), None,
                 (names[:6], r'\frac{'+b+m+'-'+q+'}{'+a+r'}\left(\frac{'+a+n+'}{'+d+'}+'+b+r'\right)'),
                 direct(names[6]), direct(names[0]), direct(names[1]), direct(names[2]), None,
                 direct(names[4]), direct(names[5])]
    elif names == ('first', 'second', 'modulus', 'start_index'):
        rules = [None, direct('first'), None, direct('second'), None, None, direct('modulus'), None]
        rules += [(('first',) if i == 0 else ('second',) if i == 1 else names[:3], 'F_{'+str(i)+'}') for i in range(6)]
        rules += [(('start_index',), symbol('start_index') + ('+'+str(i) if i else '')) for i in range(8)]
    else:
        return ()
    spans, source = context['spans'], context['problem']
    if len(spans) != len(rules):
        raise ValueError('Native coefficient display no longer matches its declared argument order')
    from .expression_patterns import MathValue
    result, offset = [], 0
    for index, (span, rule) in enumerate(zip(spans, rules)):
        start, end = span.span()
        result.append(source[offset:start])
        if rule is None:
            result.append(span[0])
        else:
            owners, formula = rule
            def evaluate(parameters, at=index, token=span):
                value = context['display'](*context['args'](parameters))[at]
                if value == int(token[0].replace(',', '')):
                    return token[0]
                text = f'{value:,}' if ',' in token[0] else str(value)
                if len(text) > 1 and source[:token.start()].rstrip().endswith(('^', '_')):
                    text = '{'+text+'}'
                return text
            result.append(SourceBindingField(MathValue(owners, evaluate, formula, formula), formula))
        offset = end
    result.append(source[offset:])
    return tuple(result)


def bind_source(template):
    """Recover fields from the renderer's explicit spans, preserving its prose.

    A native span may include both a quantity and a fixed unit, or TeX braces
    belonging to its surrounding formula. Its display expression is decomposed
    before annotation; the whole source replacement is never blindly boxed.
    """
    render = template.render
    identity = getattr(render, '__module__', ''), getattr(render, '__qualname__', '')
    derived = (_polynomial_parts(template, identity) or _loop_parts(template, identity)
               or _root_parts(template, identity) or _tex_argument_parts(template, identity)
               or _derived_coefficient_parts(template, identity))
    if derived:
        return derived
    if identity in (
            (_PREFIX + 'algebra.equations_and_expressions', '_expression_template.<locals>.<lambda>'),
            (_PREFIX + 'geometry.euclidean_and_coordinate_models', '_bind.<locals>.render')):
        return _literal_parts(template, getclosurevars(render).nonlocals, identity)
    if identity != (_PREFIX + 'algebra.source_spans', 'bind.<locals>.render'):
        return ()

    # Import lazily so the metadata adapter can also be used by the expression
    # interpreter without creating an import cycle.
    from .expression_patterns import Interpreter, MathValue, Text, Value, definition, dependencies, resolve, symbolic_tex

    context = getclosurevars(render).nonlocals
    source, spans = context['source'], context['spans']
    names = tuple(getclosurevars(context['unpack']).nonlocals['names'])
    if set(names) != set(template.parameters):
        raise ValueError('Source span arguments do not match the public parameters')
    arguments = [Value((name,), lambda parameters, key=name: parameters[key], name) for name in names]
    class SpanInterpreter(Interpreter):
        def _math(self, value):
            return getattr(value, 'math', None) or symbolic_tex(
                value.description if isinstance(value, Value) else str(value))

        def call(self, function, args, kwargs):
            identity = getattr(function, '__module__', ''), getattr(function, '__qualname__', '')
            module = _PREFIX + 'algebra.function_iterations_and_identities'
            names = dependencies((args, kwargs))
            if names and identity == (module, 'build.<locals>.expression') and len(args) == 2:
                # The native helper emits k-2k+3k-... through n*k.
                scale, count = args
                formula = (r'\sum_{i=1}^{' + self._math(count) + r'}(-1)^{i+1}'
                           + self._math(scale) + r'\,i')
                return MathValue(names, lambda p: function(*resolve(args, p), **resolve(kwargs, p)),
                                 'alternating sum through ' + count.description + ' terms', formula)
            if names and identity == (module, 'build.<locals>.additive') and len(args) == 1:
                value = args[0]
                return MathValue(names, lambda p: function(*resolve(args, p), **resolve(kwargs, p)),
                                 '+' + value.description, '+' + self._math(value))
            if names and identity == (module, 'build.<locals>.<lambda>'):
                tree = definition(function)
                def additions(node):
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                        return additions(node.left) + additions(node.right)
                    return [node]
                terms = additions(tree.body) if isinstance(tree, ast.Lambda) else []
                if len(terms) == 3:
                    opening, argument, closing = terms
                    repeated = lambda node, literal: (isinstance(node, ast.BinOp)
                        and isinstance(node.op, ast.Mult) and isinstance(node.left, ast.Constant)
                        and node.left.value == literal)
                    if (repeated(opening, 'f(') and repeated(closing, ')')
                            and ast.dump(opening.right) == ast.dump(closing.right)
                            and isinstance(argument, ast.Call) and isinstance(argument.func, ast.Name)
                            and argument.func.id == 'str' and len(argument.args) == 1 and not argument.keywords):
                        bound = signature(function).bind(*args, **kwargs)
                        bound.apply_defaults()
                        count = self.expression(opening.right, dict(bound.arguments))
                        value = self.expression(argument.args[0], dict(bound.arguments))
                        used = dependencies((count, value))
                        formula = (r'\underbrace{(f\circ f\circ\cdots\circ f)}_{'
                                   + self._math(count) + r'\text{ applications}}\left('
                                   + self._math(value) + r'\right)')
                        return MathValue(used, lambda p: function(*resolve(args, p), **resolve(kwargs, p)),
                                         'f composed ' + count.description + ' times at ' + value.description, formula)
            return super().call(function, args, kwargs)

        def expression(self, node, env, *, interpolation=False):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'replace' and not node.keywords and len(node.args) == 2
                    and all(isinstance(arg, ast.Constant) for arg in node.args)
                    and tuple(arg.value for arg in node.args) == (' ', '')):
                value = self.expression(node.func.value, env)
                if isinstance(value, Value):
                    evaluate = lambda p: value.get(p).replace(' ', '')
                    if getattr(value, 'math', None):
                        return MathValue(value.names, evaluate, value.description, value.math)
                    return Value(value.names, evaluate, value.description)
                if isinstance(value, Text):
                    return self.replace(value, (' ', ''))
                return value.replace(' ', '')
            return super().expression(node, env, interpolation=interpolation)
        def replace(self, rendered, arguments):
            if self.mathematical and not any(isinstance(part, str) and '$' in part for part in rendered.parts):
                # The native span supplies the surrounding mathematical context.
                # Preserve cross-field sign/spacing rewrites as one complete
                # mathematical fragment, never as a whole prose statement.
                names = rendered.names
                if names:
                    return MathValue(names, lambda p: rendered.get(p).replace(*arguments),
                                     self.math_label(rendered), self.symbolic_math(rendered))
                return rendered.get({}).replace(*arguments)
            return super().replace(rendered, arguments)

    interpreter = SpanInterpreter()
    parts, offset = [], 0
    for start, end, function in spans:
        if not 0 <= offset <= start < end <= len(source):
            raise ValueError('Invalid native source span')
        parts.append(source[offset:start])
        interpreter.mathematical = _inside_math(source, start, end)
        result = interpreter.call(function, arguments, {})
        fragments = result.parts if isinstance(result, Text) else (result,)
        if (interpreter.mathematical and _balanced_fragment(source[start:end])
                and any(isinstance(part, Value) and not _balanced_fragment(str(part.get(template.original)))
                        for part in fragments)):
            # Conditional native spellings may place braces at different offsets.
            # In that case the complete explicit math fragment is the smallest
            # stable unit; sharing a brace with the surrounding source is unsafe.
            dependencies = result.names
            kind = 'radical' if r'\sqrt' in source[start:end] else 'expression'
            result = Value(dependencies,
                           lambda parameters, fn=function: str(fn(*(parameters[name] for name in names))),
                           kind + '(' + ', '.join(dependencies) + ')')
            fragments = (result,)
        for fragment in fragments:
            if isinstance(fragment, Value) and fragment.names:
                parts.append(SourceBindingField(fragment, _description(fragment)))
            else:
                parts.append(str(fragment.get({}) if isinstance(fragment, Value) else fragment))
        offset = end
    parts.append(source[offset:])
    return tuple(parts)
