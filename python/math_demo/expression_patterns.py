"""Source-derived display parts for Python renderers with structural expressions.

This interpreter runs only a renderer's display program. Its deferred values
reevaluate the original Python expressions with ordinary inputs; they never
infer ownership from digits or from a diff of sampled questions.
"""
import ast
import builtins
import re
import string
import copy
import inspect
import itertools
import operator
import textwrap
from dataclasses import dataclass
from functools import lru_cache
from types import FunctionType, CodeType


@dataclass(frozen=True)
class Value:
    names: tuple
    evaluate: object
    description: str

    def get(self, params):
        return self.evaluate(params)


@dataclass(frozen=True)
class ConditionalLiteral(Value):
    control: str = ''
    predicate: object = None
    selected: object = None


@dataclass(frozen=True)
class CaseValue(Value):
    predicate: object = None
    selected: object = None
    math: object = None


@dataclass(frozen=True)
class MathValue(Value):
    math: str = ''


@dataclass(frozen=True)
class SequenceValue(Value):
    length_range: tuple = ()


@dataclass(frozen=True)
class OptionalSequence:
    entries: tuple


@dataclass(frozen=True)
class Field:
    value: Value

    @property
    def names(self):
        return self.value.names

    def label(self):
        return self.value.description

    def fill(self, params):
        return str(self.value.get(params))

    @property
    def conditional_literal(self):
        return isinstance(self.value, ConditionalLiteral)

    @property
    def control(self):
        return getattr(self.value, 'control', '')

    @property
    def symbolic_math(self):
        return getattr(self.value, 'math', None)


@dataclass(frozen=True)
class Text:
    parts: tuple

    @property
    def names(self):
        return tuple(dict.fromkeys(n for p in self.parts if isinstance(p, Value) for n in p.names))

    def get(self, params):
        return ''.join(str(resolve(p, params)) for p in self.parts)


def dependencies(value):
    if isinstance(value, (Value, Text)):
        return value.names
    if isinstance(value, (tuple, list)):
        return tuple(dict.fromkeys(n for item in value for n in dependencies(item)))
    if isinstance(value, dict):
        return tuple(dict.fromkeys(n for item in value.values() for n in dependencies(item)))
    return ()


def resolve(value, params):
    if isinstance(value, (Value, Text)):
        return value.get(params)
    if isinstance(value, (tuple, list)):
        return type(value)(resolve(item, params) for item in value)
    if isinstance(value, dict):
        return {key: resolve(item, params) for key, item in value.items()}
    return value


def text(value):
    if isinstance(value, Text):
        return value
    return Text((value,))


def concatenate(*values):
    parts = []
    for value in values:
        for part in text(value).parts:
            if isinstance(part, str) and parts and isinstance(parts[-1], str):
                parts[-1] += part
            elif part != '' if isinstance(part, str) else True:
                parts.append(part)
    return Text(tuple(parts))


def describe(node, names):
    if isinstance(node, ast.Name):
        label = node.id
    else:
        label = ast.unparse(node)
        if len(label) > 60 or '\\' in label or '\n' in label:
            label = 'expression'
    if len(names) == 1 and label == names[0]:
        return label
    return label + '(' + ', '.join(names) + ')'


def _code_signature(code):
    return (code.co_code, tuple(_code_signature(v) if isinstance(v, CodeType) else v for v in code.co_consts),
            code.co_names, code.co_varnames, code.co_freevars, code.co_cellvars,
            code.co_argcount, code.co_kwonlyargcount)


@lru_cache(maxsize=None)
def _module_source(filename):
    with open(filename, encoding="utf-8") as source:
        return ast.parse(source.read())


@lru_cache(maxsize=None)
def definition(function):
    first = 1
    parsed = _module_source(inspect.getsourcefile(function))
    if function.__name__ != '<lambda>':
        candidates = [n for n in ast.walk(parsed) if isinstance(n, ast.FunctionDef)
                      and n.name == function.__name__ and first + n.lineno - 1 == function.__code__.co_firstlineno]
        if len(candidates) == 1:
            return candidates[0]
    candidates = [n for n in ast.walk(parsed) if isinstance(n, ast.Lambda)
                  and first + n.lineno - 1 == function.__code__.co_firstlineno]
    if len(candidates) == 1:
        return candidates[0]
    # A source line may contain several lambdas, including the solver. Match
    # bytecode and constants so the display interpreter never selects by order.
    for candidate in candidates:
        assignments = [ast.Assign([ast.Name(n, ast.Store())], ast.Constant(None)) for n in function.__code__.co_freevars]
        wrapper = ast.FunctionDef('_scope', ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
                                  [*assignments, ast.Return(copy.deepcopy(candidate))], [])
        compiled = compile(ast.fix_missing_locations(ast.Module([wrapper], [])), '<display>', 'exec')
        outer = next(v for v in compiled.co_consts if isinstance(v, CodeType))
        inner = next(v for v in outer.co_consts if isinstance(v, CodeType))
        if _code_signature(inner) == _code_signature(function.__code__):
            return candidate
    raise ValueError('Ambiguous renderer source')


class Returned(Exception):
    def __init__(self, value):
        self.value = value


class Interpreter:
    def __init__(self):
        self.depth = 0

    def node_dependencies(self, node, env, bound=frozenset()):
        def direct(item):
            if isinstance(item, ast.Name) and item.id not in bound:
                return env.get(item.id)
            if isinstance(item, ast.Subscript) and isinstance(item.slice, ast.Constant):
                container = direct(item.value)
                if isinstance(container, (dict, tuple, list)):
                    try: return container[item.slice.value]
                    except (KeyError, IndexError, TypeError): pass
            return None
        if isinstance(node, ast.Name):
            return () if node.id in bound else dependencies(env.get(node.id))
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            selected = direct(node)
            if selected is not None: return dependencies(selected)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'get' and len(node.args) in (1, 2)
                and isinstance(node.args[0], ast.Constant)):
            container = direct(node.func.value)
            if isinstance(container, dict):
                selected = container.get(node.args[0].value)
                if selected is not None: return dependencies(selected)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            names, local = [], set(bound)
            for generator in node.generators:
                names.extend(self.node_dependencies(generator.iter, env, frozenset(local)))
                local.update(n.id for n in ast.walk(generator.target) if isinstance(n, ast.Name))
                for condition in generator.ifs:
                    names.extend(self.node_dependencies(condition, env, frozenset(local)))
            for child in ((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)):
                names.extend(self.node_dependencies(child, env, frozenset(local)))
            return tuple(dict.fromkeys(names))
        if isinstance(node, ast.Lambda):
            local = bound | {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
            return self.node_dependencies(node.body, env, local)
        return tuple(dict.fromkeys(name for child in ast.iter_child_nodes(node)
                                   for name in self.node_dependencies(child, env, bound)))

    def free_identifiers(self, node, bound=frozenset()):
        if isinstance(node, ast.Name):
            return {node.id} - bound if isinstance(node.ctx, ast.Load) else set()
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            names, local = set(), set(bound)
            for generator in node.generators:
                names.update(self.free_identifiers(generator.iter, frozenset(local)))
                local.update(n.id for n in ast.walk(generator.target) if isinstance(n, ast.Name))
                for condition in generator.ifs:
                    names.update(self.free_identifiers(condition, frozenset(local)))
            for child in ((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)):
                names.update(self.free_identifiers(child, frozenset(local)))
            return names
        if isinstance(node, ast.Lambda):
            local = bound | {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
            return self.free_identifiers(node.body, local)
        return set().union(*(self.free_identifiers(child, bound) for child in ast.iter_child_nodes(node)))

    def label(self, node, env, names):
        def item(value):
            if isinstance(value, Value): return value.description
            if isinstance(value, (str, int, float)): return str(value)
            return None
        def symbolic(part):
            if isinstance(part, ast.Name): return item(env.get(part.id)) or part.id
            if isinstance(part, ast.Constant): return str(part.value)
            if isinstance(part, ast.Subscript) and isinstance(part.value, ast.Name) and isinstance(part.slice, ast.Constant):
                container = env.get(part.value.id)
                if isinstance(container, (dict, tuple, list)):
                    try: return item(container[part.slice.value]) or 'value'
                    except (KeyError, IndexError, TypeError): pass
                return part.value.id + '[' + str(part.slice.value) + ']'
            if isinstance(part, ast.BinOp):
                a, b = symbolic(part.left), symbolic(part.right)
                symbols = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/', ast.FloorDiv: '//', ast.Mod: '%', ast.Pow: '^'}
                sign = symbols.get(type(part.op), '?')
                if sign == '*' and a == '1': return b
                if sign == '*' and b == '1': return a
                if sign == '+' and a == '0': return b
                if sign in ('+', '-') and b == '0': return a
                if sign == '+' and b.startswith('(') and b.endswith('-' + a + ')'):
                    return b[1:-len(a)-2]
                return '(' + a + sign + b + ')'
            if isinstance(part, ast.UnaryOp):
                return ('-' if isinstance(part.op, ast.USub) else '+') + symbolic(part.operand)
            if isinstance(part, ast.Compare):
                marks = {ast.Eq: '=', ast.NotEq: '≠', ast.Lt: '<', ast.LtE: '≤', ast.Gt: '>', ast.GtE: '≥', ast.In: ' in '}
                return symbolic(part.left) + ''.join(marks.get(type(op), '?') + symbolic(right) for op, right in zip(part.ops, part.comparators))
            if isinstance(part, ast.IfExp):
                choices = (getattr(part.body, 'value', None), getattr(part.orelse, 'value', None))
                return ('sign' if set(choices) <= {'+', '-'} else 'choice') + '(' + ', '.join(names) + ')'
            if isinstance(part, ast.Call):
                name = part.func.id if isinstance(part.func, ast.Name) else part.func.attr if isinstance(part.func, ast.Attribute) else 'value'
                if name == 'join' and part.args and isinstance(part.args[0], ast.Name):
                    name = part.args[0].id
                name = {'F': 'fraction', 'Q': 'fraction', 'Fraction': 'fraction', '_tex': 'fraction', '_tex_polynomial': 'polynomial', 'str': 'value', 'sorted': 'sequence'}.get(name, name.strip('_'))
                return name + '(' + ', '.join(names) + ')'
            return 'expression(' + ', '.join(names) + ')'
        result = symbolic(node)
        return result if len(result) <= 140 else 'expression(' + ', '.join(names) + ')'

    def native(self, node, env, label=None):
        loaded = self.free_identifiers(node)
        captured = {key: value for key, value in env.items() if key in loaded}
        names = self.node_dependencies(node, env)
        code = compile(ast.fix_missing_locations(ast.Expression(copy.deepcopy(node))), '<display-expression>', 'eval')
        def resolve_used(value, params):
            if isinstance(value, (Value, Text)):
                return value.get(params) if set(value.names) <= params.keys() else value
            if isinstance(value, (tuple, list)):
                return type(value)(resolve_used(v, params) for v in value)
            if isinstance(value, dict):
                return {key: resolve_used(v, params) for key, v in value.items()}
            return value
        def evaluate(params):
            values = {key: resolve_used(value, params) for key, value in captured.items()}
            return eval(code, values, values)
        if not names:
            return evaluate({})
        return Value(names, evaluate, label or self.label(node, env, names))

    def call(self, function, args, kwargs):
        if function is zip and all(isinstance(value, (list, tuple, range)) for value in args):
            return tuple(zip(*args, **kwargs))
        if function is enumerate and args and isinstance(args[0], (list, tuple, range)):
            return tuple(enumerate(*args, **kwargs))
        if function is len and len(args) == 1 and isinstance(args[0], (tuple, list, dict, str)):
            return len(args[0])
        if function is map and len(args) == 2 and isinstance(args[1], (tuple, list)):
            return tuple(self.call(args[0], [value], {}) for value in args[1])
        if function is iter and len(args) == 1 and isinstance(args[0], (tuple, list, dict, str)):
            return iter(args[0])
        if function is next and args and not isinstance(args[0], Value):
            return next(*args)
        if (not isinstance(function, FunctionType) or not function.__module__.startswith('template_dataset.families')
                or function.__name__ in ('_tex', '_tex_polynomial')):
            names = dependencies((args, kwargs))
            if not names:
                return function(*args, **kwargs)
            return Value(names, lambda p: function(*resolve(args, p), **resolve(kwargs, p)),
                         getattr(function, '__name__', 'expression') + '(' + ', '.join(names) + ')')
        if self.depth > 30:
            raise ValueError('Recursive display source')
        node = definition(function)
        bound = inspect.signature(function).bind(*args, **kwargs)
        bound.apply_defaults()
        env = dict(function.__globals__)
        env.update(inspect.getclosurevars(function).nonlocals)
        env.update(bound.arguments)
        self.depth += 1
        try:
            if isinstance(node, ast.Lambda):
                return self.expression(node.body, env)
            self.block(node.body, env)
        except Returned as result:
            return result.value
        finally:
            self.depth -= 1
        return None

    def expression(self, node, env, *, interpolation=False):
        if isinstance(node, ast.Name):
            return env[node.id] if node.id in env else getattr(builtins, node.id)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.JoinedStr):
            parts = []
            for item in node.values:
                if isinstance(item, ast.Constant):
                    parts.append(item.value)
                else:
                    value = self.expression(item.value, env, interpolation=True)
                    spec = '' if item.format_spec is None else self.expression(item.format_spec, env)
                    if isinstance(value, Text) and item.conversion == -1 and spec == '':
                        parts.append(value)
                        continue
                    names = dependencies((value, spec))
                    def formatted(params, v=value, s=spec, conversion=item.conversion):
                        raw = resolve(v, params)
                        if conversion == 115: raw = str(raw)
                        elif conversion == 114: raw = repr(raw)
                        elif conversion == 97: raw = ascii(raw)
                        return format(raw, resolve(s, params))
                    parts.append(Value(names, formatted, value.description if isinstance(value, Value) else self.label(item.value, env, names)) if names else formatted({}))
            return concatenate(*parts)
        if isinstance(node, ast.Subscript):
            container = self.expression(node.value, env)
            index = self.native(node.slice, env)
            if isinstance(container, (dict, tuple, list, str)) and not dependencies(index):
                return container[index]
        if interpolation:
            loaded = {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
            def has_text(value):
                return isinstance(value, Text) or isinstance(value, (tuple, list)) and any(has_text(v) for v in value)
            structural = any(isinstance(item, ast.Constant) and isinstance(item.value, str) and '$' in item.value for item in ast.walk(node))
            if not structural and not isinstance(node, ast.Call) and not any(has_text(env.get(key)) for key in loaded):
                return self.native(node, env)
        if isinstance(node, (ast.DictComp, ast.ListComp, ast.GeneratorExp)):
            rows = [dict(env)]
            for generator in node.generators:
                next_rows = []
                for row in rows:
                    iterable = self.expression(generator.iter, row)
                    if isinstance(iterable, Value):
                        if isinstance(iterable, SequenceValue) and len(node.generators) == 1 and not generator.ifs and not isinstance(node, ast.DictComp):
                            lower, upper = iterable.length_range
                            entries = []
                            for index in range(upper):
                                child = dict(row)
                                value = Value(iterable.names, lambda p, i=index, source=iterable: source.get(p)[i], iterable.description + '[' + str(index + 1) + ']')
                                self.assign(generator.target, value, child)
                                content = self.expression(node.elt, child)
                                condition = None if index < lower else Value(iterable.names, lambda p, i=index, source=iterable: len(source.get(p)) > i,
                                                                           'length(' + iterable.description + ')>' + str(index))
                                entries.append((condition, content))
                            return OptionalSequence(tuple(entries))
                        return self.native(node, env)
                    for item in iterable:
                        child = dict(row)
                        self.assign(generator.target, item, child)
                        conditions = [self.expression(c, child) for c in generator.ifs]
                        if any(isinstance(c, Value) for c in conditions):
                            return self.native(node, env)
                        if all(conditions): next_rows.append(child)
                rows = next_rows
            if isinstance(node, ast.DictComp):
                return {self.expression(node.key, row): self.expression(node.value, row) for row in rows}
            items = [self.expression(node.elt, row) for row in rows]
            return tuple(items) if isinstance(node, ast.GeneratorExp) else items
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            left = self.expression(node.left, env)
            if isinstance(left, str):
                right = self.expression(node.right, env)
                return self.percent(left, right)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = self.expression(node.left, env), self.expression(node.right, env)
            if isinstance(left, (Text, str)) or isinstance(right, (Text, str)):
                return concatenate(left, right)
            if not dependencies((left, right)):
                return left + right
            return self.native(node, env)
        if isinstance(node, (ast.List, ast.Tuple)):
            values = []
            for item in node.elts:
                value = self.expression(item.value if isinstance(item, ast.Starred) else item, env)
                if isinstance(item, ast.Starred):
                    if isinstance(value, Value): return self.native(node, env)
                    values.extend(value)
                else: values.append(value)
            return tuple(values) if isinstance(node, ast.Tuple) else values
        if isinstance(node, ast.Dict):
            return {self.expression(k, env): self.expression(v, env) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver = self.expression(node.func.value, env)
            if isinstance(receiver, Text) and not receiver.names:
                receiver = receiver.get({})
            if isinstance(receiver, Value) and isinstance(node.func.value, ast.Name) and node.func.attr in ('append', 'extend', 'insert', 'update'):
                args = [self.expression(argument, env) for argument in node.args]
                names = dependencies((receiver, args))
                def mutated(p, original=receiver, arguments=args, method=node.func.attr):
                    value = resolve(original, p)
                    getattr(value, method)(*resolve(arguments, p))
                    return value
                env[node.func.value.id] = Value(names, mutated, receiver.description)
                return None
            if isinstance(receiver, (list, dict)) and node.func.attr in ('append', 'extend', 'insert', 'setdefault', 'update'):
                args = [self.expression(arg, env) for arg in node.args]
                return getattr(receiver, node.func.attr)(*args)
            if isinstance(receiver, Text) and node.func.attr == 'split':
                separator = self.expression(node.args[0], env)
                if not isinstance(separator, str) or not separator:
                    raise ValueError('Unsupported source text split')
                chunks, current = [], []
                for item in receiver.parts:
                    if isinstance(item, str):
                        slices = item.split(separator)
                        current.append(slices[0])
                        for chunk in slices[1:]:
                            chunks.append(concatenate(*current)); current = [chunk]
                    else: current.append(item)
                return [*chunks, concatenate(*current)]
            if isinstance(receiver, str) and node.func.attr == 'join':
                sequence = self.expression(node.args[0], env)
                if isinstance(sequence, OptionalSequence):
                    pieces = []
                    for index, (condition, content) in enumerate(sequence.entries):
                        joined = concatenate(receiver if index else '', content)
                        pieces.append(joined if condition is None else self.conditional_text(condition, joined, Text(())))
                    return concatenate(*pieces)
                if isinstance(sequence, (tuple, list)) and all(isinstance(item, (str, Value, Text)) for item in sequence):
                    parts = []
                    for index, item in enumerate(sequence):
                        if index: parts.append(receiver)
                        parts.append(item)
                    return concatenate(*parts)
            if isinstance(receiver, Text) and node.func.attr == 'replace':
                args = [self.expression(arg, env) for arg in node.args]
                if dependencies(args): raise ValueError('Dynamic replacement rule')
                return self.replace(receiver, args)
            if isinstance(receiver, str) and node.func.attr == 'format':
                args = []
                for argument in node.args:
                    value = self.expression(argument.value if isinstance(argument, ast.Starred) else argument, env)
                    if isinstance(argument, ast.Starred): args.extend(value)
                    else: args.append(value)
                kwargs = {arg.arg: self.expression(arg.value, env) for arg in node.keywords}
                return self.format(receiver, args, kwargs)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'sub':
            function = self.native(node.func, env)
            if function is re.sub:
                pattern = self.expression(node.args[0], env)
                replacement = node.args[1]
                original = self.expression(node.args[2], env)
                if isinstance(pattern, str) and isinstance(original, str) and isinstance(replacement, ast.Lambda):
                    parts, offset, limit = [], 0, 0
                    for keyword in node.keywords:
                        if keyword.arg == 'count': limit = self.native(keyword.value, env)
                    for count, match in enumerate(re.finditer(pattern, original)):
                        if limit and count >= limit: break
                        local = dict(env)
                        local[replacement.args.args[0].arg] = match
                        parts.extend((original[offset:match.start()], self.expression(replacement.body, local)))
                        offset = match.end()
                    return concatenate(*parts, original[offset:])
        if isinstance(node, ast.Call):
            # Value helpers within interpolation are evaluated natively above.
            # Calls forming the prose skeleton are interpreted recursively.
            function = self.native(node.func, env)
            if isinstance(function, Value):
                return self.native(node, env)
            args = []
            for arg in node.args:
                value = self.expression(arg.value if isinstance(arg, ast.Starred) else arg, env)
                if isinstance(arg, ast.Starred): args.extend(value)
                else: args.append(value)
            kwargs = {}
            for arg in node.keywords:
                value = self.expression(arg.value, env)
                if arg.arg is None: kwargs.update(value)
                else: kwargs[arg.arg] = value
            try:
                return self.call(function, args, kwargs)
            except ValueError as error:
                if not str(error).startswith(('Unsupported display', 'Conditional early display')):
                    raise
                return self.native(node, env)
        if isinstance(node, ast.IfExp):
            condition = self.native(node.test, env)
            if not isinstance(condition, Value):
                return self.expression(node.body if condition else node.orelse, env)
            return self.merge(condition, self.expression(node.body, env), self.expression(node.orelse, env))
        return self.native(node, env)

    def percent(self, source, values):
        pattern = re.compile(r'%(?:\(([^)]+)\))?([#0\- +]*\d*(?:\.\d+)?[hlL]?[diouxXeEfFgGcrsa%])')
        parts, offset, index = [], 0, 0
        arguments = values if isinstance(values, tuple) else (values,)
        for match in pattern.finditer(source):
            parts.append(source[offset:match.start()])
            key, spec = match.groups()
            if spec == '%': parts.append('%')
            else:
                value = values[key] if key is not None else arguments[index]
                if key is None: index += 1
                names = dependencies(value)
                apply = lambda p, v=value, s='%' + spec: s % resolve(v, p)
                parts.append(Value(names, apply, value.description if isinstance(value, Value) else 'expression(' + ', '.join(names) + ')') if names else apply({}))
            offset = match.end()
        parts.append(source[offset:])
        return concatenate(*parts)

    def format(self, source, args, kwargs):
        formatter, parts, auto = string.Formatter(), [], 0
        for literal, key, spec, conversion in formatter.parse(source):
            parts.append(literal)
            if key is None: continue
            if key == '': key, auto = str(auto), auto + 1
            value, _ = formatter.get_field(key, args, kwargs)
            names = dependencies(value)
            def apply(p, v=value, s=spec, c=conversion):
                value = resolve(v, p)
                return format(formatter.convert_field(value, c) if c else value, s)
            parts.append(Value(names, apply, value.description if isinstance(value, Value) else 'expression(' + ', '.join(names) + ')') if names else apply({}))
        return concatenate(*parts)

    def replace(self, rendered, arguments):
        if any(isinstance(part, str) and arguments[0] in part for part in rendered.parts):
            return concatenate(*(part.replace(*arguments) if isinstance(part, str) else part for part in rendered.parts))
        # A post-format sign normalization can cross coefficient boundaries.
        # Apply it to complete mathematical islands; surrounding prose stays literal.
        output, inside, mathematical = [], [], False
        for part in rendered.parts:
            if isinstance(part, Value):
                if not mathematical: raise ValueError('Text rewrite outside a mathematical island')
                inside.append(part)
                continue
            pieces = re.split(r'(?<!\\)(\$)', part)
            for piece in pieces:
                if piece == '$':
                    if mathematical:
                        content = Text(tuple(inside)); names = content.names
                        output.append(Value(names, lambda p, c=content: c.get(p).replace(*arguments),
                                            self.math_label(content)) if names else content.get({}).replace(*arguments))
                        inside = []
                    output.append('$'); mathematical = not mathematical
                elif mathematical: inside.append(piece)
                else: output.append(piece.replace(*arguments))
        if mathematical: raise ValueError('Unclosed rewritten math expression')
        return concatenate(*output)

    def symbolic_math(self, rendered):
        def label(value):
            if getattr(value, 'math', None): return value.math
            escaped = value.description.replace('\\', r'\textbackslash{}').replace('_', r'\_').replace('{', r'\{').replace('}', r'\}')
            return r'\text{' + escaped + '}'
        return ''.join(label(part) if isinstance(part, Value) else part for part in rendered.parts)

    def math_label(self, rendered):
        result = ''.join(part.description if isinstance(part, Value) else part for part in rendered.parts)
        return result if len(result) <= 140 else 'expression(' + ', '.join(rendered.names) + ')'

    def merge(self, condition, yes, no):
        if not dependencies((yes, no)) and type(yes) is type(no) and yes == no:
            return yes
        if isinstance(yes, (Text, str)) or isinstance(no, (Text, str)):
            source_a, source_b = text(yes), text(no)
            prose = lambda value: len(re.findall(r'[A-Za-z]{2,}', ''.join(part for part in value.parts if isinstance(part, str)))) >= 6
            if prose(source_a) or prose(source_b):
                return self.conditional_text(condition, source_a, source_b)
            # Different mathematical/prose layouts are explicit conditional
            # branches. Their delimiters and prose are text, never value boxes.
            dollars_a = ''.join(p for p in source_a.parts if isinstance(p, str)).count('$')
            dollars_b = ''.join(p for p in source_b.parts if isinstance(p, str)).count('$')
            if dollars_a or dollars_b:
                simple = all(len(value.parts) >= 1 and isinstance(value.parts[0], str)
                             and value.parts[0].startswith('$') and isinstance(value.parts[-1], str)
                             and value.parts[-1].endswith('$') for value in (source_a, source_b))
                if not (dollars_a == dollars_b == 2 and simple):
                    return self.conditional_text(condition, source_a, source_b)
            a, b = list(text(yes).parts), list(text(no).parts)
            before, after = [], []
            while a and b and isinstance(a[0], str) and isinstance(b[0], str):
                x, y = a[0], b[0]
                index = 0
                while index < min(len(x), len(y)) and x[index] == y[index]: index += 1
                if not index: break
                before.append(x[:index]); a[0], b[0] = x[index:], y[index:]
                if not a[0]: a.pop(0)
                if not b[0]: b.pop(0)
            while a and b and isinstance(a[-1], str) and isinstance(b[-1], str):
                x, y = a[-1], b[-1]
                index = 0
                while index < min(len(x), len(y)) and x[-1-index] == y[-1-index]: index += 1
                if not index: break
                after.insert(0, x[len(x)-index:]); a[-1], b[-1] = x[:len(x)-index], y[:len(y)-index]
                if not a[-1]: a.pop()
                if not b[-1]: b.pop()
            # Do not leave an opening TeX group in the literal prefix or a
            # closing group in the suffix: keep the whole expression together.
            literal_prefix, literal_suffix = ''.join(before), ''.join(after)
            def balanced(value):
                depth = 0
                for token in re.findall(r'\\(?:[A-Za-z]+|.)|[{}]', value):
                    if token == '{': depth += 1
                    elif token == '}': depth -= 1
                    if depth < 0: return False
                return depth == 0
            if not balanced(literal_prefix) or not balanced(literal_suffix):
                before, after = [], []
                a, b = list(source_a.parts), list(source_b.parts)
            names = dependencies((condition, Text(tuple(a)), Text(tuple(b))))
            candidates = [self.math_label(Text(tuple(branch))) for branch in (a, b)]
            label = next((candidate for candidate in candidates if any(mark in candidate for mark in ('!', '\\cdots', '^', '='))),
                         'expression(' + ', '.join(names) + ')')
            selected = next((branch for branch, candidate in zip((a, b), candidates) if candidate == label), None)
            if selected is not None and any(mark in label for mark in ('!', '\\cdots', '^', '\\frac', '\\sqrt')):
                value = MathValue(names, lambda p: Text(tuple(a if condition.get(p) else b)).get(p),
                                  'formula(' + ', '.join(names) + ')', self.symbolic_math(Text(tuple(selected))))
            else:
                value = Value(names, lambda p: Text(tuple(a if condition.get(p) else b)).get(p), label)
            return concatenate(*before, value, *after)
        names = dependencies((condition, yes, no))
        return Value(names, lambda p: resolve(yes if condition.get(p) else no, p),
                     'expression(' + ', '.join(names) + ')')

    def conditional_text(self, condition, yes, no):
        parts = []
        control = condition.description
        for selected, branch in ((True, yes), (False, no)):
            header = ('If ' + control + ': ') if selected else '; otherwise: '
            parts.append(ConditionalLiteral(condition.names, lambda p: '', header, control, condition, None))
            for part in branch.parts:
                names = tuple(dict.fromkeys((*condition.names, *dependencies(part))))
                evaluate = lambda p, value=part, chosen=selected: resolve(value, p) if bool(condition.get(p)) == chosen else ''
                if isinstance(part, str):
                    parts.append(ConditionalLiteral(names, evaluate, part, control, condition, selected))
                elif isinstance(part, ConditionalLiteral):
                    parts.append(ConditionalLiteral(names, evaluate, part.description, control, condition, selected))
                else:
                    parts.append(CaseValue(names, evaluate, part.description, condition, selected, getattr(part, 'math', None)))
        return Text(tuple(parts))

    def assign(self, target, value, env):
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            starred = next((i for i, child in enumerate(target.elts) if isinstance(child, ast.Starred)), None)
            for index, child in enumerate(target.elts):
                if isinstance(child, ast.Starred):
                    end = len(target.elts) - index - 1
                    subscript = slice(index, -end if end else None)
                    child = child.value
                else:
                    subscript = index if starred is None or index < starred else index - len(target.elts)
                part = Value(value.names, lambda p, i=subscript: value.get(p)[i], value.description + '[' + str(index) + ']') if isinstance(value, Value) else value[subscript]
                self.assign(child, part, env)
        else:
            raise ValueError('Unsupported display assignment')

    def block(self, statements, env):
        for position, statement in enumerate(statements):
            if isinstance(statement, ast.Return):
                raise Returned(self.expression(statement.value, env))
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = self.expression(statement.value, env)
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for target in targets: self.assign(target, value, env)
            elif isinstance(statement, ast.If):
                condition = self.native(statement.test, env)
                if not isinstance(condition, Value):
                    self.block(statement.body if condition else statement.orelse, env)
                    continue
                forks, results = [], []
                for branch in (statement.body, statement.orelse):
                    fork = dict(env)
                    try:
                        self.block(branch, fork)
                    except Returned as result:
                        results.append(result.value)
                    else:
                        results.append(None)
                    forks.append(fork)
                if results[0] is not None or results[1] is not None:
                    for branch in range(2):
                        if results[branch] is None:
                            try:
                                self.block(statements[position + 1:], forks[branch])
                            except Returned as result:
                                results[branch] = result.value
                            else:
                                raise ValueError('Conditional early display return')
                    raise Returned(self.merge(condition, *results))
                for key in set(forks[0]) | set(forks[1]):
                    if key not in forks[0] or key not in forks[1]:
                        raise ValueError('Conditional unbound display value')
                    a, b = forks[0][key], forks[1][key]
                    if a is not b:
                        env[key] = self.merge(condition, a, b)
            elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
                equivalent = ast.BinOp(ast.Name(statement.target.id, ast.Load()), statement.op, statement.value)
                self.assign(statement.target, self.expression(equivalent, env), env)
            elif isinstance(statement, ast.For):
                iterable = self.expression(statement.iter, env)
                deferred = any(isinstance(item, ast.If) or isinstance(item, ast.AugAssign) and not isinstance(item.target, ast.Name)
                               for child in statement.body for item in ast.walk(child))
                if not isinstance(iterable, Value) and not deferred:
                    for value in iterable:
                        self.assign(statement.target, value, env)
                        self.block(statement.body, env)
                    self.block(statement.orelse, env)
                else:
                    self.deferred_block(statement, env)
            elif isinstance(statement, ast.FunctionDef):
                self.deferred_block(statement, env)
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
                continue
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                self.expression(statement.value, env)
            else:
                raise ValueError('Unsupported display statement: ' + type(statement).__name__)


    def deferred_block(self, statement, env):
        loaded = {node.id for node in ast.walk(statement) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
        changed = {node.id for node in ast.walk(statement) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
        for node in ast.walk(statement):
            if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
                root = node.value
                while isinstance(root, ast.Subscript): root = root.value
                if isinstance(root, ast.Name): changed.add(root.id)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if node.func.attr in ('append', 'extend', 'insert', 'sort', 'reverse', 'update', 'add', 'setdefault'):
                    changed.add(node.func.value.id)
        if isinstance(statement, ast.FunctionDef): changed.add(statement.name)
        captured = {key: value for key, value in env.items() if key in loaded or key in changed}
        names = dependencies(captured)
        code = compile(ast.fix_missing_locations(ast.Module([copy.deepcopy(statement)], [])), '<display-block>', 'exec')
        def evaluate(params):
            values = {key: resolve(value, params) for key, value in captured.items()}
            exec(code, values, values)
            return values
        for name in changed:
            env[name] = Value(names, lambda p, key=name: evaluate(p)[key], name + '(' + ', '.join(names) + ')') if names else evaluate({}).get(name)


def source_expression_parts(template):
    interpreter = Interpreter()
    values = {}
    for name, domain in template.parameters.items():
        length = domain.get('min_length')
        if length is not None and length == domain.get('max_length'):
            values[name] = [Value((name,), lambda p, n=name, i=index: p[n][i], name + '[' + str(index + 1) + ']') for index in range(length)]
        else:
            values[name] = (SequenceValue((name,), lambda p, n=name: p[n], name, (domain['min_length'], domain['max_length']))
                            if 'min_length' in domain and 'max_length' in domain else Value((name,), lambda p, n=name: p[n], name))
    from .source_bindings import native_display_binding
    binding = native_display_binding(template)
    rendered = interpreter.call(binding.function, list(binding.arguments(values)), {}) if binding else interpreter.call(template.render, [values], {})
    if not isinstance(rendered, Text):
        raise ValueError('Renderer did not expose a text skeleton')
    rendered = full_conditional_cases(rendered, template.parameters)
    return tuple(Field(part) if isinstance(part, Value) else str(part) for part in rendered.parts)


def full_conditional_cases(rendered, domains):
    """Keep each full source condition balanced when branches change math fences."""
    selected_parts = [part for part in rendered.parts if isinstance(part, ConditionalLiteral)
                      and part.selected is not None and '$' in part.description]
    if not selected_parts:
        return rendered
    predicates = {}
    for part in rendered.parts:
        predicate = getattr(part, 'predicate', None)
        if predicate is not None:
            predicates[predicate.description] = predicate
    keys = tuple(predicates)
    outcomes = list(itertools.product((True, False), repeat=len(keys)))
    length_rules = [re.fullmatch(r'length\(([^)]+)\)>(\d+)', key) for key in keys]
    if all(length_rules) and len({match[1] for match in length_rules}) == 1:
        domain = domains[length_rules[0][1]]
        outcomes = list(dict.fromkeys(tuple(length > int(match[2]) for match in length_rules)
                                     for length in range(domain['min_length'], domain['max_length'] + 1)))
    parts = []
    for outcome in outcomes:
        assignment = dict(zip(keys, outcome))
        names = tuple(dict.fromkeys(name for predicate in predicates.values() for name in predicate.names))
        def active(params, values=assignment):
            return all(bool(predicates[key].get(params)) == selected for key, selected in values.items())
        header = 'If ' + ' and '.join(key if selected else 'not (' + key + ')' for key, selected in assignment.items()) + ': '
        parts.append(ConditionalLiteral(names, lambda p: '', header, header))
        for part in rendered.parts:
            predicate = getattr(part, 'predicate', None)
            if predicate is not None:
                if part.selected is None or assignment[predicate.description] != part.selected:
                    continue
            if isinstance(part, str):
                parts.append(ConditionalLiteral(names, lambda p, literal=part, match=active: literal if match(p) else '', part, header))
            elif isinstance(part, ConditionalLiteral):
                parts.append(ConditionalLiteral(tuple(dict.fromkeys((*names, *part.names))),
                                               lambda p, value=part, match=active: value.get(p) if match(p) else '', part.description, header))
            else:
                parts.append(CaseValue(tuple(dict.fromkeys((*names, *part.names))),
                                       lambda p, value=part, match=active: value.get(p) if match(p) else '',
                                       part.description, math=getattr(part, 'math', None)))
        parts.append(ConditionalLiteral(names, lambda p: '', '\n\n', header))
    return Text(tuple(parts))
