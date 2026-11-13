"""Source-owned display fragments keep mathematical data separate from prose."""
import unittest

from support import ensure_runtime
ensure_runtime()
from math_demo.source_bindings import bind_source, native_display_binding
from template_dataset.registry import generate, get_template


def filled(parts, parameters):
    return ''.join(part if isinstance(part, str) else part.fill(parameters) for part in parts)


class SourceBindingTests(unittest.TestCase):
    def test_explicit_source_spans_reconstruct_original_and_seeded_conditions(self):
        for key in SOURCE_SPAN_IDS:
            template = get_template(key)
            parts = bind_source(template)
            with self.subTest(source=key):
                fields = [part for part in parts if not isinstance(part, str)]
                self.assertTrue(fields)
                self.assertTrue(all(part.names and set(part.names) <= set(template.parameters) for part in fields))
                self.assertTrue(all(part.label() and 'statement(' not in part.label() for part in fields))
            for parameters in (template.original, *(generate(key, seed)['parameters'] for seed in (0, 17, 2**64-1))):
                with self.subTest(source=key, parameters=parameters):
                    self.assertEqual(filled(parts, parameters), template.render(parameters))
                    for part in fields:
                        text = part.fill(parameters)
                        self.assertNotIn('$', text)
                        depth = 0
                        for character in text:
                            if character == '{': depth += 1
                            elif character == '}': depth -= 1
                            self.assertGreaterEqual(depth, 0, 'field owns an external closing brace')
                        self.assertEqual(depth, 0, 'field leaves a TeX group open')

    def test_literal_offsets_keep_decimal_scales_and_formula_punctuation(self):
        for key in ('algebra/train/844', 'algebra/train/1320', 'algebra/train/1697', 'prealgebra/test/234'):
            template = get_template(key)
            parts = bind_source(template)
            with self.subTest(source=key):
                fields = [part for part in parts if not isinstance(part, str)]
                self.assertEqual([part.names for part in fields], [(name,) for name in template.parameters])
                self.assertTrue(all('{' not in part.fill(template.original) for part in fields))
                for seed in (0, 17, 2**64-1):
                    parameters = generate(key, seed)['parameters']
                    self.assertEqual(filled(parts, parameters), template.render(parameters))
        template = get_template('algebra/train/844')
        fields = [part for part in bind_source(template) if not isinstance(part, str)]
        self.assertEqual([part.fill(template.original) for part in fields], ['0.03', '0.08', '20', '12.6'])
        self.assertEqual(fields[0].fill(dict(template.original, literal_1=125)), '1.25')
        self.assertEqual(fields[0].names, ('literal_1',))
        self.assertIn('100', fields[0].label())

    def test_tied_literal_occurrences_share_only_the_declared_parameter(self):
        template = get_template('algebra/train/566')
        parts = bind_source(template)
        fields = [part for part in parts if not isinstance(part, str)]
        self.assertGreaterEqual(sum(part.names == ('literal_1',) for part in fields), 3)
        parameters = dict(template.original, literal_1=7)
        self.assertEqual(filled(parts, parameters), template.render(parameters))
        self.assertTrue(all(part.fill(parameters) == '7' for part in fields if part.names == ('literal_1',)))

    def test_native_token_offsets_keep_structural_literals_and_exponent_braces(self):
        for key in ('precalculus/train/489', 'precalculus/train/730'):
            template = get_template(key)
            parts = bind_source(template)
            fields = [part for part in parts if not isinstance(part, str)]
            self.assertEqual([part.names for part in fields], [('a',), ('n',)])
            for exponent in (3, 12):
                parameters = dict(template.original, n=exponent)
                self.assertEqual(filled(parts, parameters), template.render(parameters))
                self.assertEqual(fields[1].fill(parameters), str(exponent) if exponent == 3 else '{12}')
                self.assertNotIn('$', fields[0].fill(parameters))
        template = get_template('geometry/test/145')
        parts = bind_source(template)
        fields = [part for part in parts if not isinstance(part, str)]
        self.assertEqual([part.names for part in fields], [('b',)])
        self.assertIn('1', ''.join(part for part in parts if isinstance(part, str)))
        self.assertEqual(filled(parts, template.original), template.render(template.original))

    def test_binding_metadata_calls_only_the_native_display_function(self):
        for key in WRAPPER_IDS:
            template = get_template(key)
            binding = native_display_binding(template)
            with self.subTest(source=key):
                self.assertIsNotNone(binding)
                self.assertEqual(set(binding.names), set(template.parameters))
            for parameters in (template.original, *(generate(key, seed)['parameters'] for seed in (0, 17, 2**64-1))):
                with self.subTest(source=key, parameters=parameters):
                    self.assertEqual(binding.function(*binding.arguments(parameters)), template.render(parameters))

    def test_number_words_own_numbers_and_leave_invented_units_static(self):
        template = get_template('algebra/test/18')
        parts = bind_source(template)
        fields = [part for part in parts if not isinstance(part, str)]
        self.assertEqual([(part.names, part.fill(template.original)) for part in fields], [
            (('first_treeks',), 'Ten'), (('first_squigs',), 'three'), (('second_treeks',), 'Two'),
        ])
        prose = ''.join(part for part in parts if isinstance(part, str))
        self.assertIn(' treeks', prose)
        self.assertIn(' squigs', prose)
        parameters = dict(first_treeks=13, first_squigs=7, second_treeks=5)
        self.assertEqual(filled(parts, parameters), template.render(parameters))
        self.assertTrue(all('treeks' not in part.fill(parameters) and 'squigs' not in part.fill(parameters) for part in fields))

    def test_external_tex_groups_and_limit_relation_are_static(self):
        template = get_template('algebra/test/488')
        parts = bind_source(template)
        fields = [part for part in parts if not isinstance(part, str)]
        last = fields[-1]
        self.assertEqual(last.names, ('limit',))
        self.assertEqual(last.fill(template.original), '3')
        self.assertIn('}}=', ''.join(part for part in parts if isinstance(part, str)))

    def test_factor_coefficients_have_independent_native_dependencies(self):
        template = get_template('algebra/test/190')
        fields = [part for part in bind_source(template) if not isinstance(part, str)]
        self.assertEqual([part.names for part in fields], [
            ('leading', 'middle', 'constant_magnitude'), ('first_constant',),
            ('second_scale',), ('target_scale',),
        ])
        self.assertEqual([part.fill(template.original) for part in fields[1:]], ['5', '2', '3'])

    def test_symbol_count_bound_does_not_own_the_literal_lower_bound(self):
        template = get_template('algebra/test/260')
        parts = bind_source(template)
        fields = [part for part in parts if not isinstance(part, str)]
        self.assertEqual(fields[0].names, ('maximum',))
        self.assertEqual(fields[0].fill(template.original), '9')
        self.assertIn('1 to ', ''.join(part for part in parts if isinstance(part, str)))

    def test_fraction_pairs_keep_argument_order_and_independent_quantity_ownership(self):
        from math_demo.presentation import atomic_presentation

        key = 'prealgebra/train/275'
        template = get_template(key)
        parameters = dict(template.original)
        changed = dict(parameters, numerator_1=7)
        before, after = (atomic_presentation(key, p) for p in (parameters, changed))
        self.assertEqual(before['scope'], 'native-fields')
        self.assertEqual(after['scope'], 'native-fields')
        self.assertEqual(''.join(part['text'] for part in before['segments']), template.render(parameters))
        self.assertEqual(''.join(part['text'] for part in after['segments']), template.render(changed))
        affected = []
        for first, second in zip(before['segments'], after['segments']):
            if first['kind'] != 'parameter':
                self.assertEqual(first, second)
                continue
            owners = set(first['parameters'])
            self.assertTrue(owners <= {'numerator_1', 'denominator_1'} or
                            owners <= {'numerator_2', 'denominator_2'})
            self.assertFalse(any(word in first['text'] for word in ('Compute', 'minus', 'Give your answer')))
            if first['text'] != second['text']:
                affected.append(first)
                self.assertIn('numerator_1', owners)
            elif 'numerator_1' not in owners:
                self.assertEqual(first['text'], second['text'])
        self.assertTrue(affected)

    def test_duration_phrase_does_not_claim_unused_rotation_or_target_inputs(self):
        template = get_template('algebra/test/786')
        fields = [part for part in bind_source(template) if not isinstance(part, str)]
        duration = [part for part in fields if part.fill(template.original) == 'one day']
        self.assertEqual(len(duration), 1)
        self.assertEqual(duration[0].names, ('elapsed_hours',))
        self.assertEqual(duration[0].fill(dict(template.original, elapsed_hours=7)), '7 hours')


SOURCE_SPAN_IDS = ('algebra/test/0', 'algebra/test/18', 'algebra/test/22', 'algebra/test/141', 'algebra/test/190', 'algebra/test/202', 'algebra/test/216', 'algebra/test/260', 'algebra/test/324', 'algebra/test/329', 'algebra/test/351', 'algebra/test/435', 'algebra/test/461', 'algebra/test/488', 'algebra/test/510', 'algebra/test/610', 'algebra/test/611', 'algebra/test/687', 'algebra/test/772', 'algebra/test/786', 'algebra/test/849', 'algebra/test/879', 'algebra/test/984', 'algebra/test/993', 'algebra/test/999', 'algebra/test/1002', 'algebra/test/1012', 'algebra/test/1056', 'algebra/test/1083', 'algebra/test/1092', 'algebra/test/1155', 'algebra/test/1160', 'algebra/test/1185')
WRAPPER_IDS = ('algebra/train/97', 'algebra/train/108', 'algebra/train/129', 'algebra/train/135', 'algebra/train/138', 'algebra/train/158', 'algebra/train/189', 'algebra/train/192', 'algebra/train/210', 'algebra/train/255', 'algebra/train/262', 'algebra/train/318', 'algebra/train/414', 'algebra/train/554', 'algebra/train/603', 'algebra/train/656', 'algebra/train/679', 'algebra/train/698', 'algebra/train/707', 'algebra/train/718', 'algebra/train/724', 'algebra/train/734', 'algebra/train/774', 'algebra/train/805', 'algebra/train/916', 'algebra/train/935', 'algebra/train/943', 'algebra/train/961', 'algebra/train/1006', 'algebra/train/1068', 'algebra/train/1078', 'algebra/train/1199', 'algebra/train/1223', 'algebra/train/1230', 'algebra/train/1262', 'algebra/train/1265', 'algebra/train/1301', 'algebra/train/1303', 'algebra/train/1312', 'algebra/train/1434', 'algebra/train/1439', 'algebra/train/1441', 'algebra/train/1480', 'algebra/train/1520', 'algebra/train/1533', 'algebra/train/1541', 'algebra/train/1580', 'algebra/train/1646', 'algebra/train/1661', 'prealgebra/train/36', 'prealgebra/train/149', 'prealgebra/train/200', 'prealgebra/train/256', 'prealgebra/train/275', 'prealgebra/train/468', 'prealgebra/train/535', 'prealgebra/train/682', 'prealgebra/train/686', 'prealgebra/train/718', 'prealgebra/train/731', 'prealgebra/train/778', 'prealgebra/train/808', 'prealgebra/train/809', 'prealgebra/train/863', 'prealgebra/train/901', 'prealgebra/train/978', 'prealgebra/train/1005', 'prealgebra/train/1122', 'prealgebra/train/1129', 'prealgebra/train/1182', 'prealgebra/train/1185', 'algebra/test/198', 'algebra/test/341', 'algebra/test/387', 'algebra/test/398', 'algebra/test/464', 'algebra/test/466', 'algebra/test/482', 'algebra/test/483', 'algebra/test/825', 'algebra/test/848', 'algebra/test/962', 'algebra/test/1075', 'algebra/test/1084', 'algebra/test/1135', 'prealgebra/test/82', 'prealgebra/test/125', 'prealgebra/test/153', 'prealgebra/test/163', 'prealgebra/test/390', 'prealgebra/test/423', 'prealgebra/test/502', 'prealgebra/test/505', 'prealgebra/test/586', 'prealgebra/test/587', 'prealgebra/test/631', 'prealgebra/test/632', 'prealgebra/test/791')
