"""Independent semantic and browser checks for complete, meaningful patterns.

Expected conditions and elementary answers are written from the mathematics,
not copied from the presentation extractor's symbolic intermediate objects.
"""
from fractions import Fraction
import json
import tempfile
import unittest

from support import HAS_BROWSER, ensure_runtime, prepare_browser, run_browser, static_origin
ensure_runtime()
from math_demo.presentation import atomic_presentation, presentation
from template_dataset.registry import get_template
from composite_dataset import build_schema
from composite_dataset.profiles import get_catalogue


CASES = (
    ('counting_and_probability/train/77', 'What is the units digit'),
    ('counting_and_probability/train/187', 'How many'),
    ('intermediate_algebra/test/200', 'For positive real'),
    ('algebra/train/53', 'If'),
    ('prealgebra/train/175', 'Express'),
    ('prealgebra/train/534', 'Billy opens'),
    ('algebra/train/264', 'Define'),
    ('number_theory/train/176', 'Convert'),
    ('algebra/train/1312', 'A scale drawing'),
    ('algebra/train/272', 'Express'),
    ('prealgebra/train/436', 'Compute'),
    ('precalculus/train/489', 'If'),
    ('precalculus/train/730', 'If'),
    ('prealgebra/train/801', 'Express'),
    ('algebra/test/341', 'Find'),
    ('algebra/train/192', 'The roots'),
    ('precalculus/test/266', 'The cube'),
)


def condition(result):
    return ''.join(part.get('symbolic_math', part['text']) for part in result['segments'])


def owned_spans(result):
    offset = 0
    for part in result['segments']:
        end = offset + len(part['text'])
        if part['kind'] == 'parameter' and end > offset:
            yield offset, end, set(part['parameters']), part['text']
        offset = end


class CompletePatternSemanticTests(unittest.TestCase):
    def checked(self, source, params, expected, answer, prefix):
        bare = atomic_presentation(source)
        self.assertNotEqual(bare['scope'], 'computed-statement')
        self.assertIn(prefix, condition(bare))
        self.assertNotIn('statement(', condition(bare))
        self.assertTrue(any(part['kind'] == 'parameter' for part in bare['segments']))
        filled = atomic_presentation(source, params)
        self.assertEqual(condition(filled), expected)
        self.assertEqual(get_template(source).render(params), expected)
        self.assertEqual(Fraction(get_template(source).solve(params)), Fraction(answer))
        self.assertIn(prefix, ''.join(part['text'] for part in filled['segments'] if part['kind'] == 'text'))
        self.assertTrue(list(owned_spans(filled)))
        return filled

    def region(self, result, fragment, names, *, all_characters=True, start=None):
        start = condition(result).index(fragment) if start is None else start
        stop = start + len(fragment)
        spans = [row for row in owned_spans(result) if row[0] < stop and row[1] > start]
        self.assertTrue(spans, f'No parameter owns {fragment!r}')
        self.assertEqual(set().union(*(row[2] for row in spans)), set(names))
        self.assertTrue(all(start <= row[0] < row[1] <= stop for row in spans),
                        f'Ownership of {fragment!r} includes its literal surroundings')
        if all_characters:
            for position in range(start, stop):
                if condition(result)[position].isalnum():
                    self.assertTrue(any(a <= position < b for a, b, _, _ in spans),
                                    f'Unowned character in {fragment!r}')

    def literal(self, result, fragment):
        start = condition(result).index(fragment)
        end = start + len(fragment)
        self.assertFalse(any(a < end and b > start for a, b, _, _ in owned_spans(result)),
                         f'A parameter colors literal {fragment!r}')

    def test_factorial_sum_has_visible_rule_and_short_branch_is_exact(self):
        source = 'counting_and_probability/train/77'
        bare = condition(atomic_presentation(source))
        self.assertIn('count', bare)
        self.assertTrue('!' in bare and any(token in bare for token in ('1!', r'\sum', '∑')),
                        'The bare factorial sum is hidden behind an opaque expression label')
        for count, expression, answer in (
            (3, '1! + 2! + 3!', 9),
            (4, '1! + 2! + 3! + 4!', 3),
            (274, r'1! + 2! + 3! + \cdots + 274!', 3),
        ):
            with self.subTest(count=count):
                result = self.checked(source, {'count': count},
                    f'What is the units digit of ${expression}$?', answer, 'What is the units digit')
                self.region(result, expression, {'count'}, all_characters=False)

    def test_alphabet_slice_sort_and_join_have_exact_dependencies(self):
        for params, letters, answer in (
            ({'length': 8, 'vowels': 4, 'consonants': 1}, 'A, B, E, I, O', 390624),
            ({'length': 2, 'vowels': 1, 'consonants': 2}, 'A, B, C', 5),
        ):
            with self.subTest(params=params):
                result = self.checked('counting_and_probability/train/187', params,
                    f"How many {params['length']}-letter strings from {letters} contain at least one vowel? Letters can be reused.",
                    answer, 'How many')
                self.region(result, str(params['length']), {'length'})
                self.region(result, letters, {'vowels', 'consonants'})
                self.literal(result, 'one vowel? Letters can be reused.')

    def test_amgm_coefficients_do_not_own_literal_cubic_exponents(self):
        # AM-GM on 3x^3, 2y^3, (243/2)z^3 gives 3*cuberoot(729)=27.
        expected = r'For positive real $x,y,z$, find the minimum of $\frac{3 x^3+2 y^3+\frac{243}{2} z^3}{xyz}$.'
        result = self.checked('intermediate_algebra/test/200', {'a': 3, 'b': 2, 'c': '243/2'},
                              expected, 27, 'For positive real')
        self.region(result, '3', {'a'})
        self.region(result, '2', {'b'})
        self.region(result, r'\frac{243}{2}', {'c'})
        for literal in ('x^3', 'y^3', 'z^3', '{xyz}'):
            self.literal(result, literal)

    def test_positive_zero_and_negative_optional_offset_keep_literal_prose(self):
        for offset, tail, answer in ((4, '+4', 66), (0, '', 62), (-4, '-4', 58)):
            with self.subTest(offset=offset):
                expected = r'If $m+\frac{1}{m}=8$, find $m^{2}+\left(\frac{1}{m}\right)^{2}' + tail + '$.'
                result = self.checked('algebra/train/53',
                    {'sum': 8, 'product': 1, 'power': 2, 'offset': offset}, expected, answer, 'If')
                self.literal(result, ', find ')
                self.assertTrue(all('$' not in text for _, _, _, text in owned_spans(result)))

    def test_fraction_attributes_preserve_exact_decimal_and_sign(self):
        for numerator, denominator, decimal in ((29, 20, '1.45'), (-3, 8, '-0.375'), (8, 4, '2')):
            with self.subTest(n=numerator, d=denominator):
                result = self.checked('prealgebra/train/175',
                    {'numerator': numerator, 'denominator': denominator},
                    f'Express ${decimal}$ as a fraction in lowest terms.', Fraction(numerator, denominator), 'Express')
                self.region(result, decimal, {'numerator', 'denominator'})

    def test_variable_list_length_and_repeated_values_keep_the_same_owner(self):
        for counts, listed in (([2, 2, 8], '2, 2, 8'), ([1, 2, 3, 10], '1, 2, 3, 10')):
            with self.subTest(counts=counts):
                expected = f'Billy opens {len(counts)} packages and counts the cookies in each. The counts are {listed}. What is the average number of cookies per package?'
                result = self.checked('prealgebra/train/534', {'counts': counts}, expected, 4, 'Billy opens')
                self.region(result, str(len(counts)), {'counts'})
                self.region(result, listed, {'counts'})

    def test_literal_variable_replacement_does_not_own_the_definition(self):
        expected = r'Define $a*b=\frac{1}{a}+\frac{1}{b}$ for nonzero integers. If $a+b=7$ and $ab=10$, find $a*b$ as a common fraction.'
        result = self.checked('algebra/train/264', {'s': 7, 'p': 10}, expected, Fraction(7, 10), 'Define')
        self.region(result, '7', {'s'})
        self.region(result, '10', {'p'})
        self.literal(result, r'a*b=\frac{1}{a}+\frac{1}{b}')

    def test_digit_lookup_does_not_color_literal_target_base_ten(self):
        result = self.checked('number_theory/train/176',
            {'base': 16, 'digit_1': 10, 'digit_2': 0, 'digit_3': 3},
            r'Convert $A03_{16}$ to base 10.', 2563, 'Convert')
        self.region(result, 'A03', {'digit_1', 'digit_2', 'digit_3'})
        self.region(result, '16', {'base'})
        self.literal(result, 'to base 10.')

    def test_divmod_and_decimal_padding_retain_trailing_zero(self):
        expected = 'A scale drawing shows that one inch represents 800 feet. How many feet does a segment measuring 4.50 inches represent?'
        result = self.checked('algebra/train/1312', {'scale': 800, 'map_hundredths': 450}, expected, 3600, 'A scale drawing')
        self.region(result, '800', {'scale'})
        self.region(result, '4.50', {'map_hundredths'})

    def test_dynamic_format_width_and_leading_zeroes_have_both_dependencies(self):
        result = self.checked('algebra/train/272', {'digits': 3, 'width': 2},
            r'Express $0.\overline{03}$ as a fraction in lowest terms.', Fraction(1, 33), 'Express')
        self.region(result, '03', {'digits', 'width'})
        self.literal(result, '0.')

    def test_mixed_number_square_root_is_addition_not_multiplication(self):
        for whole, answer in ((156, Fraction(25, 2)), (12, Fraction(7, 2))):
            with self.subTest(whole=whole):
                # 156+1/4=625/4 and 12+1/4=49/4; these are mixed numbers.
                result = self.checked('prealgebra/train/801',
                    {'whole_part': whole, 'fraction_numerator': 1, 'fraction_denominator': 4},
                    rf'Express $\sqrt{{{whole}\frac{{1}}{{4}}}}$ as a reduced fraction.', answer, 'Express')
                self.region(result, str(whole), {'whole_part'})
                self.region(result, r'\frac{1}{4}', {'fraction_numerator', 'fraction_denominator'}, all_characters=False)

    def test_determinant_power_uses_real_parameter_names_across_exponent_braces(self):
        fixtures = (
            ('precalculus/train/489', 1, r'If $\det \mathbf{A} = 2,$ then find $\det (\mathbf{A^1}).$'),
            ('precalculus/train/489', 12, r'If $\det \mathbf{A} = 2,$ then find $\det (\mathbf{A^{12}}).$'),
            ('precalculus/train/730', 1, r'If $\det \mathbf{M} = 2,$ then find $ \det (\mathbf{M}^1).$'),
            ('precalculus/train/730', 12, r'If $\det \mathbf{M} = 2,$ then find $ \det (\mathbf{M}^{12}).$'),
        )
        for source, exponent, expected in fixtures:
            with self.subTest(source=source, exponent=exponent):
                # det(A^n)=det(A)^n, independently of dimension or entries.
                result = self.checked(source, {'a': 2, 'n': exponent}, expected,
                                      2 if exponent == 1 else 4096, 'If')
                self.region(result, '2', {'a'})
                self.region(result, '1' if exponent == 1 else '{12}', {'n'})
        for source in ('precalculus/train/489', 'precalculus/train/730'):
            schema = build_schema(1, 1, 0, split='train', catalogue={source: get_catalogue()[source]})
            node = presentation(schema)['nodes'][0]
            self.assertIn(r'\det', condition(node))
            self.assertNotRegex(condition(node) + ' '.join(node['notes']), r'fragment\s*\d|Insert fragment|\bR\d+\.')
            owners = {name for part in node['segments'] if part['kind'] == 'parameter' for name in part['parameters']}
            self.assertEqual(owners, {'a', 'n'})

    def test_decimal_product_pattern_is_not_a_numbered_fragment_lookup(self):
        bare = atomic_presentation('prealgebra/train/436')
        self.assertNotRegex(condition(bare) + ' '.join(bare['notes']), r'fragment\s*\d|Insert fragment|\bR\d+\.')
        for n1, n2, first, second, answer in ((4, 6, '0.4', '0.6', Fraction(6, 25)),
                                              (10, 15, '1.0', '1.5', Fraction(3, 2))):
            with self.subTest(n1=n1, n2=n2):
                result = self.checked('prealgebra/train/436', {'n1': n1, 'n2': n2},
                    rf'Compute $\left({first} \cdot {second}\right)$.', answer, 'Compute')
                self.region(result, first, {'n1'})
                self.region(result, second, {'n2'})
                self.literal(result, r'\cdot')
        schema = build_schema(1, 1, 1204, split='train')
        self.assertEqual(schema['nodes'][0]['source_id'], 'prealgebra/train/436')
        node = presentation(schema)['nodes'][0]
        self.assertIn('Compute', condition(node))
        self.assertIn(r'\cdot', condition(node))
        self.assertNotRegex(condition(node) + ' '.join(node['notes']), r'fragment\s*\d|Insert fragment|\bR\d+\.')


@unittest.skipUnless(HAS_BROWSER, 'Requires Playwright with Chromium, or native macOS WebKit and Clang')
class CompletePatternBrowserTests(unittest.TestCase):
    def test_every_adversarial_case_has_a_real_bare_condition_fill_and_reset(self):
        with tempfile.TemporaryDirectory(prefix='math-demo-complete-patterns-') as folder:
            runner = prepare_browser(folder)
            with static_origin() as server:
                output = run_browser(runner, server.url, 'const cases = ' + json.dumps(CASES) + r''';
                  await until(idleAtomic, "runtime");
                  const settled = async () => until(() => !$("atomic-renderer-note").hidden ||
                    [...$("atomic-problem-text").querySelectorAll(".math-fragment")].every(node => node.hasAttribute("data-rendered")),
                    "math", {timeout: 20000});
                  for (const [source, prefix] of cases) {
                    const [subject, split] = source.split("/");
                    if ($("atomic-subject").value !== subject) { change("atomic-subject", subject); await until(idleAtomic, "subject"); }
                    if ($("atomic-split").value !== split) { change("atomic-split", split); await until(idleAtomic, "split"); }
                    change("atomic-problem-id", source); await until(idleAtomic, source + " bare"); await settled();
                    const target = $("atomic-problem-text");
                    const bare = target.textContent;
                    check(bare.includes(prefix), source + " hides the bare condition");
                    check(!/statement\(|после заполнения параметров|fragment\s*\d|Insert fragment/.test(bare), source + " exposes a fallback or lookup label");
                    check(target.querySelector(".parameter-slot, [data-parameters]"), source + " has no visible symbolic inputs");
                    if (source.endsWith("/train/77")) check(bare.includes("!") && bare.includes("count"), "Bare factorial sum is opaque");
                    check($("atomic-answer-value").textContent === "—", source + " is not initially bare");
                    if (!$("atomic-seed-mode").checked) $("atomic-seed-mode").click();
                    $("atomic-seed").value = "17";
                    $("atomic-generate").click(); await until(idleAtomic, source + " filled"); await settled();
                    check(target.textContent.includes(prefix) && target.textContent !== bare, source + " did not fill its condition");
                    check($("atomic-answer-value").textContent !== "—", source + " has no visible answer");
                    check(target.querySelector(".slot-filled, [data-parameters]"), source + " lost inline input ownership");
                    if (source === "prealgebra/train/801") {
                      const tex = target.querySelector("annotation").textContent;
                      check(tex.includes("\\,") && !tex.includes("\\cdot") && !tex.includes("\\times"),
                            "Mixed number lost its visual gap or became a product");
                    }
                    $("atomic-reset").click(); await settled();
                    check(target.textContent === bare, source + " reset changed the complete pattern");
                  }
                  $("composite-tab").click(); await until(idleComposite, "composite activation");
                  $("composite-depth").value = "1"; $("composite-width").value = "1";
                  $("composite-structure-seed-mode").click(); $("composite-structure-seed").value = "1204";
                  $("composite-structure-random").click(); await until(idleComposite, "real decimal-product leaf");
                  const card = document.querySelector(".subproblem-card");
                  check(card.querySelector(".subproblem-origin").textContent.includes("№ 436"), "Composite fixture selected the wrong source");
                  const statement = card.querySelector(".subproblem-statement");
                  await until(() => [...statement.querySelectorAll(".math-fragment")].every(node => node.hasAttribute("data-rendered")), "leaf math");
                  const bareLeaf = statement.textContent;
                  check(bareLeaf.includes("Compute") && bareLeaf.includes("n1") && bareLeaf.includes("n2"), "Leaf hides its actual decimal-product pattern");
                  check(!/fragment\s*\d|Insert fragment|\bR\d+\./.test(card.textContent), "Leaf exposes coding aliases or a lookup table");
                  $("composite-parameter-random").click(); await until(idleComposite, "filled leaf");
                  check(document.querySelector(".subproblem-answer"), "Filled leaf has no answer");
                  $("composite-reset-parameters").click();
                  const resetStatement = document.querySelector(".subproblem-statement");
                  await until(() => [...resetStatement.querySelectorAll(".math-fragment")].every(node => node.hasAttribute("data-rendered")), "reset leaf math");
                  check(resetStatement.textContent === bareLeaf, "Leaf reset changed its real pattern");
                  return "OK: complete real patterns, inline ownership and reset for all adversarial cases";
                ''', timeout=360)
                self.assertIn('OK:', output)
