"""Native TeX display environments and explicit bare math in the real browser."""
import json
import tempfile
import unittest

from support import HAS_BROWSER, ensure_runtime, prepare_browser, run_browser, static_origin


@unittest.skipUnless(HAS_BROWSER, 'Requires Playwright Chromium or native macOS WebKit')
class TexEnvironmentBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='math-demo-tex-environments-')
        cls.addClassCleanup(temporary.cleanup)
        cls.runner = prepare_browser(temporary.name)

    def render_case(self, script):
        with static_origin() as server:
            result = run_browser(self.runner, server.url + '__renderer_test__.html', script, timeout=60)
        self.assertIn('OK', result)

    def test_actual_line_segment_pattern_and_instance_in_atomic_and_composite(self):
        ensure_runtime()
        from math_demo.presentation import atomic_presentation, presentation
        from template_dataset.registry import get_template
        from composite_dataset import build_schema
        from composite_dataset.profiles import get_catalogue
        source = 'precalculus/train/338'
        template = get_template(source)
        params = {'x': -2, 'y': 7, 'u': 3, 'v': 11}
        filled = atomic_presentation(source, params)
        self.assertEqual(''.join(part['text'] for part in filled['segments']), template.render(params))
        catalogue = get_catalogue()
        leaves = [key for key, profiles in sorted(catalogue.items())
                  if '/train/' in key and len(profiles[0]['parameter_names']) == 1][:4]
        selected = {key: catalogue[key] for key in [source, *leaves]}
        schema = build_schema(2, 4, 17, catalogue=selected)
        self.assertEqual(schema['nodes'][0]['source_id'], source)
        variants = [atomic_presentation(source), filled]
        for seed in (None, 17):
            variants.append(next(node for node in presentation(schema, seed)['nodes'] if node['source_id'] == source))
        self.render_case('const variants = ' + json.dumps(variants) + r''';
          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          for (const [index, variant] of variants.entries()) {
            check(await MathPresentation.render(target, variant.segments), 'Native line-segment formula failed: ' + index);
            const block = target.querySelector('.math-display');
            check(block?.querySelector('.katex-html .mtable'), 'Standalone align* remained plain text: ' + index);
            check(target.querySelectorAll('.math-display').length === 1, 'Native align* was wrapped more than once');
            check(!target.querySelector('.math-fragment .math-fragment, .katex-error, [data-rendered="false"]'), 'Nested or failed formula');
            const source = block.querySelector('annotation').textContent;
            check(source.startsWith('\\begin{align*}') && source.endsWith('\\end{align*}'), 'Native environment delimiters were lost');
            check(source.includes('x &= at + b') && source.includes('y &= ct + d'), 'Parametric equations changed');
            check(target.querySelectorAll('.math-fragment:not(.math-display) .katex').length >= 2, 'Adjacent inline formulas disappeared');
            const keys = [...target.querySelectorAll('[data-parameters]')].flatMap(element => element.dataset.parameters.split(' '));
            for (const name of ['x', 'y', 'u', 'v']) {
              check(keys.some(key => key === name || key.endsWith('.' + name)), 'Coordinate placeholder lost: ' + name);
            }
          }
          return 'OK: actual atomic and internal composite align* patterns and instances';
        ''')

    def test_standalone_display_environments_nested_blocks_and_existing_delimiters(self):
        self.render_case(r'''
          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          const formulas = [
            ...['align', 'align*'].map(name => `\\begin{${name}}x&=1\\\\y&=2\\end{${name}}`),
            ...['equation', 'equation*'].map(name => `\\begin{${name}}x=1\\end{${name}}`),
            ...['gather', 'gather*'].map(name => `\\begin{${name}}x=1\\\\y=2\\end{${name}}`),
            ...['alignat', 'alignat*'].map(name => `\\begin{${name}}{2}x&=1&y&=2\\\\z&=3&w&=4\\end{${name}}`),
            '\\begin{CD}A @>a>> B \\\\ @VbVV @AAcA \\\\ C @= D\\end{CD}',
            '\\begin{equation}\\begin{split}x&=1+2\\\\&=3\\end{split}\\end{equation}',
            '\\begin{align*}x&=1% ignored \\end{align*}\n\\\\y&=2\\end{align*}',
          ];
          for (const formula of formulas) {
            check(await MathPresentation.render(target, [{kind: 'text', text: 'Before $z$ ' + formula + ' after \\(w\\).'}]), 'Supported environment failed: ' + formula);
            check(target.querySelectorAll('.math-fragment').length === 3, 'Environment or adjacent inline range lost');
            check(target.querySelectorAll('.math-display .katex').length === 1, 'Standalone environment was not one display formula');
            check(target.querySelector('.math-display annotation').textContent === formula, 'Environment source was rewritten or truncated');
          }
          for (const wrapped of ['\\[\\begin{aligned}x&=1\\\\y&=2\\end{aligned}\\]',
                                 '$$' + formulas[1] + '$$', '\\[' + formulas[4] + '\\]']) {
            check(await MathPresentation.render(target, [{kind: 'text', text: wrapped}]), 'Delimited environment failed');
            check(target.querySelectorAll('.math-fragment').length === 1, 'Existing math delimiters caused double wrapping');
          }
          return 'OK: supported native environments with balanced nesting and existing delimiters';
        ''')

    def test_slots_inside_environments_preserve_bare_and_filled_ownership(self):
        self.render_case(r'''
          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          const literal = text => ({kind: 'text', text});
          const parameter = (name, text, filled, role = 'external') => ({kind: 'parameter', name, key: name, text, role, filled});
          for (const filled of [false, true]) {
            const segments = [literal('\\begin{align*}x&='), parameter('a', filled ? '3' : 'a', filled),
              literal('t+'), parameter('b', filled ? '\\frac{7}{2}' : 'b', filled, 'internal'), literal('\\end{align*}')];
            check(await MathPresentation.render(target, segments), 'Environment parameter failed');
            check(target.querySelectorAll('.math-display .fbox').length === 2, 'Parameter boxes were lost or duplicated');
            check(target.querySelector('.math-display').dataset.parameters === 'a b', 'Parameter ownership changed');
            const source = target.querySelector('annotation').textContent;
            check(source.includes('\\color{#2463b3}') && source.includes('\\color{#945512}'), 'External/internal roles changed');
          }
          return 'OK: bare and filled environment slots retain both parameter roles';
        ''')

    def test_explicit_bare_symbolic_math_outside_delimiters_is_typeset_once(self):
        self.render_case(r'''
          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          const literal = text => ({kind: 'text', text});
          const parameter = (name, text, filled) => ({kind: 'parameter', name, key: name, text, role: 'external', filled});
          const symbolic = {...parameter('vectors', 'vectors', false), symbolic_math: '\\left(\\vec v_1,\\ldots,\\vec v_k\\right)'};
          for (const [before, after] of [['Vectors: ', '.'], ['Vectors: $', '$.']]) {
            check(await MathPresentation.render(target, [literal(before), symbolic, literal(after)]), 'Bare symbolic slot failed');
            check(target.querySelectorAll('.math-fragment').length === 1, 'Bare symbolic slot was not exactly one formula');
            check(target.querySelectorAll('.fbox').length === 1, 'Bare symbolic slot was boxed more than once');
            check(target.querySelector('annotation').textContent.includes('\\vec'), 'Bare symbolic math was escaped as plain text');
          }
          await MathPresentation.render(target, [literal('Label: '), {...symbolic, symbolic_math: '$ hidden $'}]);
          check(!target.querySelector('.math-fragment') && !target.textContent.includes('hidden'), 'Unsafe symbolic metadata became math');
          return 'OK: standalone explicit symbolic slots render without duplicate wrapping';
        ''')

    def test_structural_table_body_is_not_boxed_across_alignment_boundaries(self):
        self.render_case(r'''
          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          const segments = [
            {kind: 'text', text: '\\begin{equation*}\\begin{array}{r|l}'},
            {kind: 'parameter', text: '1&2\\\\3&4', name: 'scores', key: 'scores', role: 'external', filled: true},
            {kind: 'text', text: '\\end{array}\\end{equation*}'},
          ];
          check(await MathPresentation.render(target, segments), 'Native array body stopped rendering');
          check(target.querySelector('.katex-html .mtable'), 'Table structure was lost');
          check(!target.querySelector('.fbox'), 'One box crossed native row/alignment boundaries');
          check(target.querySelector('annotation').textContent === segments.map(part => part.text).join(''), 'Structural table source changed');
          return 'OK: exact native table without unsafe cross-row ownership';
        ''')

    def test_native_tabular_cells_keep_headers_percentages_blanks_and_parameters(self):
        ensure_runtime()
        from math_demo.presentation import atomic_presentation
        from template_dataset import generate
        sources = ['prealgebra/test/635', 'prealgebra/train/150',
                   'prealgebra/train/32', 'prealgebra/train/637']
        variants = [{'id': source, 'view': atomic_presentation(source, params)}
                    for source in sources for params in (None, generate(source, 0)['parameters'])]
        self.render_case('const variants = ' + json.dumps(variants) + r''';
          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          for (const {id, view} of variants) {
            const original = JSON.stringify(view.segments);
            check(await MathPresentation.render(target, view.segments), 'Native table failed: ' + id);
            check(target.querySelectorAll('table').length === 1, 'Missing native table: ' + id);
            check(!target.textContent.includes('\\begin{tabular}') && !target.textContent.includes('\\hline'), 'Raw table commands remain');
            check(JSON.stringify(view.segments) === original, 'Renderer mutated exported/native segments');
            const keys = new Set([...target.querySelectorAll('[data-parameter]')].map(e => e.dataset.parameter));
            for (const e of target.querySelectorAll('[data-parameters]')) for (const key of e.dataset.parameters.split(' ')) keys.add(key);
            for (const part of view.segments.filter(p => p.kind === 'parameter')) check(keys.has(part.key), 'Table slot lost: ' + part.key);
            const rows = [...target.querySelectorAll('tr')].map(row => [...row.cells].map(cell => cell.textContent.trim()));
            if (id.endsWith('/635')) {
              check(rows.length === 5 && target.querySelector('td[colspan="2"]'), 'Blank spanning table header lost');
              check(rows.slice(1).every(row => row[1].endsWith('%')), 'Percent signs lost');
            } else if (id.endsWith('/150')) {
              check(target.querySelectorAll('strong').length === 2, 'Bold column headings lost');
              check(rows.length === 4 && rows[0][0] === 'Type of Car', 'Car table headings/rows changed');
              check(target.querySelectorAll('td .katex').length === 4, 'Math in table cells lost');
            } else if (id.endsWith('/32')) {
              check(rows.length === 4 && rows.every(row => row.length === 3), 'Survey dimensions changed');
              check(rows[0][0] === '' && rows[1][2] === '' && rows[2][1] === '', 'Missing survey values were invented');
              check(target.querySelector('tr td').style.textAlign === 'left', 'Column alignment lost');
            } else check(rows.length === 5 && rows.every(row => row[1].endsWith('feet')), 'Roller-coaster measurements lost');
          }
          return 'OK: all four native tables, bare and filled, retain real cells and ownership';
        ''')

    def test_table_colspan_text_safety_and_malformed_source_fallback(self):
        self.render_case(r'''          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          const source = '\\begin{tabular}{|l|r|}\\multicolumn{2}{c}{\\textbf{<img src=x>}}\\\\A\\&B&7\\%\\\\\\end{tabular}';
          check(await MathPresentation.render(target, [{kind:'text',text:source}]), 'Spanning header failed');
          check(target.querySelector('td[colspan="2"] strong')?.textContent === '<img src=x>', 'Spanning text header changed');
          check(!target.querySelector('img') && target.querySelector('tr:last-child td').textContent === 'A&B', 'Table text was interpreted as HTML or alignment');
          check(target.querySelector('tr:last-child td:last-child').textContent === '7%', 'Escaped percentage changed');
          for (const text of ['\\begin{tabular}{lr}a&b', '\\begin{tabular}{lr}a&b&c\\\\\\end{tabular}',
                              '\\begin{tabular}{p{2cm}}a\\\\\\end{tabular}']) {
            check(await MathPresentation.render(target, [{kind:'text',text}]), 'Malformed literal failed');
            check(!target.querySelector('table') && target.textContent === text, 'Unsupported table was partly consumed');
          }
          return 'OK: table parsing keeps exact unsupported input and safe literal text';
        ''')

    def test_compact_fraction_arguments_are_not_merged_by_an_annotation(self):
        self.render_case(r'''          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          for (const prefix of ['\\frac', '\\frac ', '\\dfrac', '\\tfrac']) {
            const segments = [{kind:'text',text:'$'+prefix},
              {kind:'parameter',name:'digits',key:'digits',text:'18',role:'external',filled:true}, {kind:'text',text:'$'}];
            check(await MathPresentation.render(target, segments), 'Compact fraction arguments merged');
            const frac = target.querySelector('.katex-mathml mfrac');
            check(frac && frac.children[0].textContent === '1' && frac.children[1].textContent === '8', 'Compact fraction meaning changed');
          }
          const separated = [{kind:'text',text:'$\\frac'},
            {kind:'parameter',name:'n',key:'n',text:'1',role:'external',filled:true},
            {kind:'parameter',name:'d',key:'d',text:'8',role:'internal',filled:true},{kind:'text',text:'$'}];
          check(await MathPresentation.render(target, separated), 'Separate fraction slots failed');
          check(target.querySelectorAll('.fbox').length === 2, 'Safe one-argument fraction slots lost emphasis');
          return 'OK: compact native arguments retain meaning with joint and separate annotations';
        ''')

    def test_literal_unicode_relations_in_bare_labels_are_safe_text(self):
        self.render_case(r'''          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          const label = 'a≠1; b≤2; c≥0; x∈S; \\htmlClass{evil}{x}';
          check(await MathPresentation.render(target, [{kind:'text',text:'$'},
            {kind:'parameter',name:'label',key:'label',text:label,role:'external',filled:false},{kind:'text',text:'$'}]), 'Unicode relation broke a plain label');
          check(target.querySelectorAll('.fbox').length === 1 && !target.querySelector('.evil'), 'Plain label was promoted to executable TeX');
          check(target.querySelector('.katex-mathml').textContent.includes('≠'), 'Literal relation disappeared');
          return 'OK: ordinary labels preserve Unicode relations without TeX injection';
        ''')

    def test_invalid_unknown_escaped_and_failed_environments_preserve_literal_text(self):
        self.render_case(r'''
          const {MathPresentation} = await import('./math-renderer.js');
          const target = document.createElement('div'); document.body.append(target);
          for (const value of ['\\begin{align*}x=1', '\\begin{align}x=1\\end{gather}',
                               '\\begin{verbatim}literal\\end{verbatim}', '\\\\begin{align}x=1\\\\end{align}']) {
            check(await MathPresentation.render(target, [{kind: 'text', text: value}]), 'Non-math literal failed');
            check(target.textContent === value && !target.querySelector('.math-fragment'), 'Literal or malformed environment was consumed');
          }
          window.katex = {render: () => { throw new Error('Renderer unavailable'); }};
          const segments = [
            {kind: 'text', text: 'Before \\begin{align*}x&='},
            {kind: 'parameter', text: 'a', key: 'a', name: 'a', role: 'external', filled: false},
            {kind: 'text', text: '\\end{align*} after <img src=x onerror=alert(1)>.'},
          ];
          check(await MathPresentation.render(target, segments) === false, 'Failed renderer incorrectly reported success');
          check(target.textContent === segments.map(part => part.text).join(''), 'Fallback lost exact native text');
          check(target.querySelector('[data-parameter="a"]') && !target.querySelector('img'), 'Fallback lost safe parameter ownership');
          return 'OK: malformed environments stay literal and failed rendering preserves exact text';
        ''')


if __name__ == '__main__':
    unittest.main()
