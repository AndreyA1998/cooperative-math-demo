"""A symbolic condition must expose the mathematics behind derived fields."""
from fractions import Fraction
import json
import re
import tempfile
import unittest
from support import HAS_BROWSER, ensure_runtime, prepare_browser, run_browser, static_origin
ensure_runtime()
from math_demo.presentation import atomic_presentation
from template_dataset.registry import get_template, registry


def visible(presentation):
    return ''.join(segment.get('symbolic_math', segment['text']) for segment in presentation['segments'])


class SymbolicMeaningTests(unittest.TestCase):
    def test_conditional_quadratic_keeps_its_actual_polynomial_in_both_bare_branches(self):
        source = 'algebra/train/192'
        bare = atomic_presentation(source)
        formulas = [part['symbolic_math'] for part in bare['segments'] if part.get('symbolic_math')]
        self.assertEqual(len(formulas), 2)
        for formula in formulas:
            plain = re.sub(r'\\text\{([^{}]+)\}', r'\1', formula).replace(' ', '')
            self.assertEqual(plain, 'ax^2+bx+c')
        self.assertNotRegex(visible(bare), r'expression\(|polynomial\(')
        for a, b, c, mode, answer in ((3, -7, 3, 1, 26), (2, -5, -4, 0, 57)):
            params = dict(a=a, b=b, c=c, sum_coefficients=mode)
            # Quadratic formula: (7±sqrt(13))/6 or (5±sqrt(57))/4.
            polynomial = '3x^2 - 7x + 3' if mode else '2x^2 - 5x - 4'
            tail = ('integers $m,n,p$, positive $p$, and $\\gcd(m,n,p)=1$. Find $m+n+p$.' if mode
                    else 'positive integers $m,n,p$ and $\\gcd(m,n,p)=1$. Find $n$.')
            expected = 'The roots of $ ' + polynomial + '=0$ have the form $x=(m\\pm\\sqrt{n})/p$, with ' + tail
            self.assertEqual(visible(atomic_presentation(source, params)), expected)
            self.assertEqual(get_template(source).render(params), expected)
            self.assertEqual(Fraction(get_template(source).solve(params)), answer)

    def test_alphabet_prefixes_are_explicit_not_an_opaque_join(self):
        for source in ('counting_and_probability/train/187', 'counting_and_probability/train/251'):
            bare = visible(atomic_presentation(source))
            self.assertIn('the first vowels letters of AEIOU', bare)
            self.assertIn('the first consonants letters of BCDFGHJK', bare)
            self.assertNotRegex(bare, r'join\(|sorted\(|expression\(')
        params = {'length': 8, 'vowels': 4, 'consonants': 1}
        expected = 'How many 8-letter strings from A, B, E, I, O contain at least one vowel? Letters can be reused.'
        self.assertEqual(visible(atomic_presentation('counting_and_probability/train/187', params)), expected)
        self.assertEqual(Fraction(get_template('counting_and_probability/train/187').solve(params)), 5**8 - 1)

    def test_formatting_is_expressed_as_mathematics_and_source_sequences(self):
        cases = {
            'intermediate_algebra/test/200': ('a', 'b', 'c', 'x^3'),
            'prealgebra/train/175': ('decimal expansion of (numerator)/(denominator)',),
            'algebra/train/1312': ('decimal expansion of (map_hundredths)/100',),
            'prealgebra/train/534': ('number of entries in counts', 'entries of counts'),
            'number_theory/train/176': ('digit_1', 'digit_2', 'digit_3', 'A–F'),
            'precalculus/test/266': ('planes[1]', 'planes[2]', 'planes[3]', '0 → x=y', '1 → y=z', '2 → z=x'),
        }
        for source, fragments in cases.items():
            with self.subTest(source=source):
                bare = visible(atomic_presentation(source))
                self.assertNotRegex(bare, r'(?:expression|str|divmod|join|_?tex|_?tex_polynomial)\(')
                for fragment in fragments: self.assertIn(fragment, bare)
                template = get_template(source)
                self.assertEqual(visible(atomic_presentation(source, template.original)), template.render(template.original))
        signed = visible(atomic_presentation('algebra/train/53'))
        self.assertNotRegex(signed, r'(?:expression|str|choice)\(')
        self.assertIn(r'+\text{offset}', signed)
        for offset in (-4, 0, 4):
            params = {'sum': 8, 'product': 1, 'power': 2, 'offset': offset}
            result = atomic_presentation('algebra/train/53', params)
            self.assertEqual(visible(result), get_template('algebra/train/53').render(params))
            self.assertEqual(Fraction(get_template('algebra/train/53').solve(params)), 62 + offset)

    def test_source_fraction_shorthand_and_clock_branches_are_readable(self):
        bare = visible(atomic_presentation('algebra/test/324'))
        self.assertIn(r'\frac{\text{numerator}}{\text{denominator}}', bare)
        self.assertNotIn('25 when', bare)
        clock = visible(atomic_presentation('algebra/test/786'))
        self.assertIn('(degrees, elapsed_hours)=(360, 24)', clock)
        self.assertIn('elapsed_hours', clock)
        self.assertIn('target_hours', clock)
        self.assertNotRegex(clock, r'expression\(|join\(')
        for source in ('algebra/test/324', 'algebra/test/786', 'precalculus/test/347', 'intermediate_algebra/test/858'):
            template = get_template(source)
            self.assertNotRegex(visible(atomic_presentation(source)), r'expression\(|tex_fraction\(')
            self.assertEqual(visible(atomic_presentation(source, template.original)), template.render(template.original))

    def test_concatenated_factors_are_products_and_signed_terms_are_sums(self):
        for source in ('intermediate_algebra/test/62','intermediate_algebra/test/856'):
            bare=visible(atomic_presentation(source))
            self.assertEqual(bare.count(r'\prod_{j=1}'),2)
            self.assertIn(r'\text{roots}_j',bare)
            self.assertIn(r'\text{numerator\_powers}_j',bare)
            self.assertIn(r'\text{denominator\_powers}_j',bare)
            template=get_template(source)
            self.assertEqual(visible(atomic_presentation(source,template.original)),template.render(template.original))
        source='algebra/train/554';params={'base':3,'terms':5}
        self.assertIn(r'\sum_{i=1}^{\text{terms}}\frac{(-1)^{i-1}}{\text{base}^{i}}',visible(atomic_presentation(source)))
        self.assertEqual(Fraction(get_template(source).solve(params)),Fraction(61,243))

    def test_unit_denominators_and_coefficients_are_mathematics_not_formatting_cases(self):
        sources = ('prealgebra/test/125','prealgebra/test/631','prealgebra/test/82',
                   'prealgebra/train/1005','prealgebra/train/1182','prealgebra/train/149',
                   'prealgebra/train/275','prealgebra/train/731','prealgebra/train/808','prealgebra/train/863')
        for source in sources:
            bare=atomic_presentation(source);template=get_template(source)
            fields=[part for part in bare['segments'] if part['kind']=='parameter']
            for field in fields:
                if any(name.startswith('denominator_') for name in field['parameters']):
                    self.assertIn(r'\frac{\text{numerator\_',field['symbolic_math'])
                    self.assertNotIn('otherwise',field['symbolic_math'])
            for denominator in (1,3):
                params={name:(denominator if name.startswith('denominator_') else value) for name,value in template.original.items()}
                self.assertEqual(visible(atomic_presentation(source,params)),template.render(params))
        source='intermediate_algebra/train/668';bare=atomic_presentation(source)
        field=next(part for part in bare['segments'] if part.get('parameters')==['equation_scale'])
        self.assertEqual(field['symbolic_math'],r'\text{equation\_scale}')
        self.assertNotIn('omitted otherwise',visible(bare))
        for scale in (1,3):
            params={'root_scale':5,'equation_scale':scale,'shift':-2}
            self.assertEqual(visible(atomic_presentation(source,params)),get_template(source).render(params))
            # From z^3+t²z=t³, reduction gives z^7+2t^5z²=t^7.
            self.assertEqual(Fraction(get_template(source).solve(params)),scale**2*5**7)

    def test_compact_products_and_vector_sequence_are_explicit(self):
        cases = {
            'algebra/train/734': (r'\prod_{j=0}^{\text{start\_offset}}(a-j)', {'start_offset':3,'argument':5}, 120),
            'intermediate_algebra/test/729': (r'\prod_{j=0}^{2}', {'start':1,'step':2,'length':6,'degree':5}, 36),
            'precalculus/train/297': (r'\text{vectors}_{3i+1}', {'vectors':[1,0,0,0,1,0,0,0,1]}, 2),
        }
        for source,(formula,params,answer) in cases.items():
            with self.subTest(source=source):
                bare=atomic_presentation(source)
                self.assertIn(formula, visible(bare))
                self.assertNotIn('join(', visible(bare))
                template=get_template(source)
                self.assertEqual(visible(atomic_presentation(source,params)),template.render(params))
                self.assertEqual(Fraction(template.solve(params)),answer)

    def test_txt_export_fences_standalone_symbolic_math_without_double_fencing(self):
        from math_demo.api import plain_template_text
        segment={'kind':'parameter','text':'formula','symbolic_math':r'\frac{a}{b}'}
        self.assertEqual(plain_template_text([{'kind':'text','text':'Given '},segment,{'kind':'text','text':', solve.'}]),r'Given $\frac{a}{b}$, solve.')
        self.assertEqual(plain_template_text([{'kind':'text','text':'Given $'},segment,{'kind':'text','text':'$, solve.'}]),r'Given $\frac{a}{b}$, solve.')
        self.assertEqual(plain_template_text([{'kind':'text','text':r'\begin{align*}x='},segment,{'kind':'text','text':r'\end{align*}'}]),r'\begin{align*}x=\frac{a}{b}\end{align*}')
        text=plain_template_text(atomic_presentation('precalculus/train/297')['segments'])
        self.assertIn(r'be $\left(',text)
        self.assertIn('$, in that order.',text)

    def test_every_bare_condition_exposes_its_math_without_service_aliases(self):
        opaque = re.compile(r'(?:expression|statement|join|_?tex(?:_polynomial)?|get|len|chr|polynomial|formula|str|divmod|choice|value|term|factor)\(|(?:expression|fragment)\s+\d+')
        for source in registry():
            with self.subTest(source=source):
                bare = atomic_presentation(source)
                self.assertEqual(bare['scope'], 'native-fields')
                for segment in bare['segments']:
                    if segment['kind'] != 'parameter': continue
                    display = segment.get('symbolic_math',segment['text'])
                    self.assertNotRegex(display,opaque)
                    self.assertNotIn('__display',display.replace(r'\_','_'))
                    self.assertNotIn('Value(',display)
        from math_demo.expression_patterns import text_tex
        self.assertEqual(text_tex('i%2 & n_1'),r'\text{i\%2 \& n\_1}')

    def test_polynomial_and_fraction_formatters_preserve_argument_structure(self):
        # _tex_polynomial stores coefficients in increasing exponent order;
        # display-only lifting must preserve both their order and dependencies.
        from math_demo.expression_patterns import formatter_meaning, Value
        from template_dataset.families.algebra.equations_and_expressions import _tex_polynomial, _tex
        a = Value(('a',), lambda p: p['a'], 'a')
        b = Value(('b',), lambda p: p['b'], 'b')
        label = lambda value: value.description if isinstance(value, Value) else str(value)
        self.assertIsNone(formatter_meaning(', '.join, [a], {}, label))
        self.assertEqual(formatter_meaning(_tex, [a], {}, label), ('a', r'\text{a}'))
        formula = formatter_meaning(_tex_polynomial, [[a, b, 1]], {}, label)[1]
        self.assertEqual(formula, r'x^{2} + \text{b}x + \text{a}')
        self.assertEqual(formatter_meaning(Fraction, [a, b], {}, label), ('(a)/(b)', r'\frac{\text{a}}{\text{b}}'))
        numerator = Value(('a', 'b'), lambda p: p['a'] + p['b'], 'a+b')
        denominator = Value(('c', 'd'), lambda p: p['c'] + p['d'], 'c+d')
        description, formula = formatter_meaning(Fraction, [numerator, denominator], {}, label)
        self.assertEqual(description, '(a+b)/(c+d)')
        self.assertEqual(formula, r'\frac{(\text{a}+\text{b})}{(\text{c}+\text{d})}')
        from template_dataset.families.word_problems.decimal_arithmetic import decimal
        self.assertEqual(formatter_meaning(decimal, [numerator], {}, label)[0], 'decimal expansion of (a+b)/100')


    def test_format_specs_keep_signs_digit_widths_and_coordinate_names(self):
        for source, expected in (
            ('algebra/train/1263', '+constant'),
            ('algebra/train/1316', 'squared_number'),
            ('precalculus/test/393', 'P[1]'),
            ('algebra/train/43', '3 digits, including leading zeros'),
        ):
            with self.subTest(source=source):
                text = visible(atomic_presentation(source))
                self.assertIn(expected, text)
                self.assertNotRegex(text, r'(?:signed|literal|grouped|pad)\(')
                template = get_template(source)
                self.assertEqual(visible(atomic_presentation(source, template.original)), template.render(template.original))

    def test_conditional_word_is_explicit_and_does_not_hide_its_source_choices(self):
        bare = visible(atomic_presentation('algebra/test/387'))
        self.assertIn('even when step=2', bare)
        self.assertIn('omitted otherwise', bare)
        self.assertNotRegex(bare, r'(?:choice|expression)\(')
        for params, word, answer in (({'total': 66, 'count': 3, 'step': 2}, 'even ', 20),
                                     ({'total': 49, 'count': 7, 'step': 1}, '', 4)):
            expected = f"The sum of {params['count']} consecutive {word}integers is {params['total']}. What is the smallest?"
            self.assertEqual(visible(atomic_presentation('algebra/test/387', params)), expected)
            self.assertEqual(Fraction(get_template('algebra/test/387').solve(params)), answer)

    def test_original_radical_spelling_does_not_freeze_its_parameters(self):
        from math_demo.expression_patterns import source_expression_parts
        source = 'algebra/test/435'
        template = get_template(source)
        parts = source_expression_parts(template)
        formulas = [part.symbolic_math for part in parts if not isinstance(part, str) and part.symbolic_math]
        self.assertTrue(formulas)
        symbolic = ' '.join(formulas)
        for name in ('index', 'base', 'exponent'): self.assertIn(name, symbolic)
        self.assertNotIn(r'\sqrt[12]{8^4}', symbolic)
        for params in ({'index': 12, 'base': 8, 'exponent': 4}, {'index': 3, 'base': 8, 'exponent': 1}):
            self.assertEqual(''.join(part if isinstance(part, str) else part.fill(params) for part in parts), template.render(params))

    def test_repeated_sum_shows_the_summand_and_repetition_count(self):
        source = 'algebra/test/464'
        bare = visible(atomic_presentation(source))
        self.assertIn('base', bare)
        self.assertIn('term_count', bare.replace(r'\_', '_'))
        self.assertIn('^x', bare)
        self.assertIn(r'\underbrace', bare)
        self.assertNotIn('join(', bare)
        params = {'base': 2, 'term_count': 4, 'rhs': 32}
        self.assertEqual(visible(atomic_presentation(source, params)), 'Find $x$ if $2^x+2^x+2^x+2^x=32$.')
        self.assertEqual(Fraction(get_template(source).solve(params)), 3)

    def test_native_literal_numbers_remain_literal_text(self):
        for source in ('algebra/train/224','algebra/train/589','intermediate_algebra/test/636'):
            template=get_template(source);bare=atomic_presentation(source)
            self.assertNotRegex(visible(bare),r'\bexpression\s+\d+')
            self.assertEqual(visible(atomic_presentation(source,template.original)),template.render(template.original))
            literal=''.join(part['text'] for part in bare['segments'] if part['kind']=='text')
            self.assertRegex(literal,r'\d')

    def test_literal_formatted_lookup_keys_do_not_erase_polynomial_or_prime_inputs(self):
        from math_demo.expression_patterns import Interpreter, Value
        import ast
        coefficient = Value(('coefficient',), lambda p: p['coefficient'], 'coefficient')
        result = Interpreter().expression(ast.parse("p[f'c{0}']", mode='eval').body, {'p': {'c0': coefficient}})
        self.assertEqual(result.names, ('coefficient',))
        self.assertEqual(result.get({'coefficient': -7}), -7)
        for source in ('algebra/test/307', 'algebra/train/1371', 'algebra/train/470',
                       'intermediate_algebra/test/834', 'number_theory/test/474',
                       'number_theory/test/503', 'number_theory/train/190', 'number_theory/train/234',
                       'number_theory/train/429', 'number_theory/train/451', 'number_theory/train/488',
                       'number_theory/train/717'):
            with self.subTest(source=source):
                template = get_template(source)
                self.assertEqual(atomic_presentation(source)['scope'], 'native-fields')
                self.assertEqual(visible(atomic_presentation(source, template.original)), template.render(template.original))


@unittest.skipUnless(HAS_BROWSER, 'Requires Playwright with Chromium, or native macOS WebKit and Clang')
class SymbolicMeaningBrowserTests(unittest.TestCase):
    def test_quadratic_formula_and_explicit_alphabet_survive_fill_and_reset(self):
        with tempfile.TemporaryDirectory(prefix='math-demo-symbolic-meaning-') as folder:
            runner = prepare_browser(folder)
            with static_origin() as server:
                output = run_browser(runner, server.url, r'''
                  await until(idleAtomic, "empty startup");
                  change("atomic-subject", "algebra"); await until(idleAtomic, "quadratic subject");
                  change("atomic-split", "train"); await until(idleAtomic, "quadratic split");
                  change("atomic-problem-id", "algebra/train/192"); await until(idleAtomic, "conditional quadratic");
                  const settled = async () => {
                    await until(() => [...$("atomic-problem-text").querySelectorAll(".math-fragment")].every(node => node.hasAttribute("data-rendered")), "symbolic typesetting");
                    check($("atomic-renderer-note").hidden, "Meaningful formula failed KaTeX");
                  };
                  const quadratic = () => {
                    const formulas = [...$("atomic-problem-text").querySelectorAll("annotation")].map(node => node.textContent).join("\n");
                    check(formulas.includes("x^2") && formulas.includes("\\text{a}") && formulas.includes("\\text{b}") && formulas.includes("\\text{c}"), "Bare quadratic hides its real coefficients or powers");
                    check(!/expression\(|polynomial\(/.test($("atomic-problem-text").textContent), "Opaque quadratic helper is visible");
                  };
                  await settled(); quadratic();
                  $("atomic-generate").click(); await until(idleAtomic, "filled quadratic"); await settled();
                  check($("atomic-answer-value").textContent !== "—", "Filled quadratic has no answer");
                  $("atomic-reset").click(); await settled(); quadratic();
                  change("atomic-subject", "counting_and_probability"); await until(idleAtomic, "counting subject");
                  change("atomic-split", "train"); await until(idleAtomic, "counting train");
                  change("atomic-problem-id", "counting_and_probability/train/187"); await until(idleAtomic, "alphabet pattern");
                  const alphabet = () => {
                    const text = $("atomic-problem-text").textContent;
                    check(text.includes("the first vowels letters of AEIOU") && text.includes("the first consonants letters of BCDFGHJK"), "Bare alphabet hides the actual source letters");
                    check(!/join\(|sorted\(|expression\(/.test(text), "Opaque alphabet helper is visible");
                  };
                  alphabet();
                  $("atomic-seed-mode").click(); $("atomic-seed").value = "287";
                  $("atomic-generate").click(); await until(idleAtomic, "filled alphabet");
                  check($("atomic-problem-text").textContent.includes("A, B, E, I, O"), "Actual alphabet is wrong");
                  check($("atomic-answer-value").textContent === "390624", "Actual alphabet answer is wrong");
                  $("atomic-reset").click(); await settled(); alphabet();
                  for (const source of ["intermediate_algebra/test/200", "prealgebra/train/175", "algebra/train/53", "algebra/train/1312", "prealgebra/train/534", "number_theory/train/176", "precalculus/test/266"]) {
                    const [subject, split] = source.split("/");
                    change("atomic-subject", subject); await until(idleAtomic, "formatter subject");
                    change("atomic-split", split); await until(idleAtomic, "formatter split");
                    change("atomic-problem-id", source); await until(idleAtomic, "formatter template");
                    await settled();
                    const bare = $("atomic-problem-text").textContent;
                    check(!/(?:expression|str|divmod|join|_?tex|_?tex_polynomial)\(/.test(bare), source + ": opaque formatting helper is visible");
                    $("atomic-generate").click(); await until(idleAtomic, "formatter fill"); await settled();
                    check($("atomic-answer-value").textContent !== "—", source + ": filled answer missing");
                    $("atomic-reset").click(); await settled();
                    check($("atomic-problem-text").textContent === bare, source + ": reset lost symbolic semantics");
                  }
                  return "OK: real symbolic mathematics and explicit source sequences, fill and reset";
                ''')
                self.assertIn('OK:', output)
