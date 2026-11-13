"""Display the source spans and argument bindings declared by native renderers.

These adapters read rendering metadata only. They never call a solver, infer
ownership from matching digits, or change a native function or its globals.
"""
from dataclasses import dataclass
from inspect import getclosurevars
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
    """Public parameter names replace incidental native names such as a/b/c."""
    names = expression.names
    if len(names) == 1:
        return names[0]
    label = expression.description
    operation = next((name for name in ('polynomial', 'fraction', 'decimal', 'radical', 'signed')
                      if name in label), 'expression')
    return operation + '(' + ', '.join(names) + ')'



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


def bind_source(template):
    """Recover fields from the renderer's explicit spans, preserving its prose.

    A native span may include both a quantity and a fixed unit, or TeX braces
    belonging to its surrounding formula. Its display expression is decomposed
    before annotation; the whole source replacement is never blindly boxed.
    """
    render = template.render
    identity = getattr(render, '__module__', ''), getattr(render, '__qualname__', '')
    if identity in (
            (_PREFIX + 'algebra.equations_and_expressions', '_expression_template.<locals>.<lambda>'),
            (_PREFIX + 'geometry.euclidean_and_coordinate_models', '_bind.<locals>.render')):
        return _literal_parts(template, getclosurevars(render).nonlocals, identity)
    if identity != (_PREFIX + 'algebra.source_spans', 'bind.<locals>.render'):
        return ()

    # Import lazily so the metadata adapter can also be used by the expression
    # interpreter without creating an import cycle.
    from .expression_patterns import Interpreter, Text, Value

    context = getclosurevars(render).nonlocals
    source, spans = context['source'], context['spans']
    names = tuple(getclosurevars(context['unpack']).nonlocals['names'])
    if set(names) != set(template.parameters):
        raise ValueError('Source span arguments do not match the public parameters')
    arguments = [Value((name,), lambda parameters, key=name: parameters[key], name) for name in names]
    class SpanInterpreter(Interpreter):
        def replace(self, rendered, arguments):
            if self.mathematical and not any(isinstance(part, str) and '$' in part for part in rendered.parts):
                # The native span supplies the surrounding mathematical context.
                # Preserve cross-field sign/spacing rewrites as one complete
                # mathematical fragment, never as a whole prose statement.
                names = rendered.names
                if names:
                    return Value(names, lambda p: rendered.get(p).replace(*arguments), self.math_label(rendered))
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
