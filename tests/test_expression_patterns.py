"""Source dependency tests independent of catalogue values or text equality."""
import ast
import unittest
from support import ensure_runtime
ensure_runtime()
from math_demo.expression_patterns import Interpreter, Value


class ExpressionDependencyTests(unittest.TestCase):
    def value(self, name):
        return Value((name,), lambda p: p[name], name)

    def test_literal_subscript_owns_only_the_accessed_parameter(self):
        env = {'p': {name: self.value(name) for name in ('a', 'b', 'unused')}}
        result = Interpreter().native(ast.parse('p["a"] ** 2', mode='eval').body, env)
        self.assertEqual(result.names, ('a',))
        self.assertEqual(result.get({'a': 7}), 49)

    def test_comprehension_local_does_not_capture_shadowed_outer_parameter(self):
        env = {'p': {'x': self.value('unused')}, 'x': self.value('also_unused')}
        result = Interpreter().native(ast.parse('sum(p["x"] for p in [{"x": 1}])', mode='eval').body, env)
        self.assertEqual(result, 1)
        result = Interpreter().native(ast.parse('sum(x for x in range(4))', mode='eval').body, env)
        self.assertEqual(result, 6)

    def test_finite_iterator_consumes_distinct_parameter_values(self):
        interpreter = Interpreter()
        iterator = interpreter.call(iter, [(self.value('a'), self.value('b'))], {})
        a = interpreter.call(next, [iterator], {})
        b = interpreter.call(next, [iterator], {})
        self.assertEqual((a.names, b.names), (('a',), ('b',)))
        self.assertEqual((a.get({'a': 3}), b.get({'b': 5})), (3, 5))
