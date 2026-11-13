"""First activation is lazy, restore-aware, and suppressed by the brand reset."""
import asyncio
import os
import unittest

from support import HAS_PLAYWRIGHT, ROOT, static_origin
from test_view_state_review import TRANSPORT


@unittest.skipUnless(HAS_PLAYWRIGHT, 'Requires server Chromium')
class FirstActivationTests(unittest.TestCase):
    def run_page(self, exercise, *, suffix='', delayed=None):
        from playwright.async_api import async_playwright
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.cache/ms-playwright'))

        async def run(url):
            async with async_playwright() as engine:
                browser = await engine.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    transport = TRANSPORT.replace(
                        "  let data;",
                        "  if (path === window.__delayPath) await new Promise(resolve => window.__releaseRequest = resolve);\n  let data;")
                    await page.route('**/transport.js', lambda route: route.fulfill(content_type='text/javascript', body=transport))
                    await page.route('**/math-renderer.js', lambda route: route.fulfill(content_type='text/javascript', body='export const MathPresentation={render:async(node,parts)=>{node.textContent=parts.map(p=>p.text).join("");return true;}};'))
                    if delayed:
                        await page.add_init_script('window.__delayPath = ' + repr(delayed))
                    await page.goto(url + suffix)
                    await exercise(page, url)
                    self.assertFalse(errors, errors)
                finally:
                    await browser.close()

        with static_origin() as server:
            asyncio.run(run(server.url))

    async def idle(self, page, view):
        await page.wait_for_function("view => !document.getElementById(view === 'atomic' ? 'atomic-catalogue-controls' : 'composite-structure-controls').disabled && document.getElementById(view + '-status').hidden", arg=view, timeout=10000)

    async def paths(self, page):
        return await page.evaluate('window.__reviewPaths ?? []')

    def test_each_view_auto_selects_once_only_when_first_activated(self):
        async def exercise(page, _url):
            await self.idle(page, 'atomic')
            self.assertTrue(await page.locator('#atomic-problem-card').is_visible())
            self.assertEqual(await page.locator('#atomic-answer-value').inner_text(), '—')
            self.assertNotIn('/api/composite/build', await self.paths(page))
            await page.locator('#composite-tab').click()
            await self.idle(page, 'composite')
            self.assertTrue(await page.locator('#composite-schema-results').is_visible())
            self.assertEqual(await page.locator('#composite-root-answer').inner_text(), '—')
            for prefix in ('atomic', 'composite-structure', 'composite-parameter'):
                self.assertFalse(await page.locator('#' + prefix + '-seed-mode').is_checked())
            await page.locator('#atomic-tab').click()
            await page.locator('#composite-tab').click()
            self.assertEqual((await self.paths(page)).count('/api/template'), 1)
            self.assertEqual((await self.paths(page)).count('/api/composite/build'), 1)
            self.assertNotIn('/api/generate', await self.paths(page))
            self.assertNotIn('/api/composite/variant', await self.paths(page))
        self.run_page(exercise)

    def test_direct_composite_link_keeps_atomic_unselected_until_activation(self):
        async def exercise(page, _url):
            await self.idle(page, 'composite')
            self.assertTrue(await page.locator('#composite-schema-results').is_visible())
            await self.idle(page, 'atomic')
            self.assertEqual(await page.locator('#atomic-problem-id').input_value(), '')
            self.assertNotIn('/api/template', await self.paths(page))
            await page.locator('#atomic-tab').click()
            await self.idle(page, 'atomic')
            self.assertTrue(await page.locator('#atomic-problem-card').is_visible())
        self.run_page(exercise, suffix='#composite')

    def test_rapid_tab_switches_do_not_duplicate_pending_build(self):
        async def exercise(page, _url):
            await self.idle(page, 'atomic')
            await page.locator('#composite-tab').click()
            await page.wait_for_function("typeof window.__releaseRequest === 'function'", timeout=10000)
            await page.evaluate("() => { for (let i=0;i<5;i++) { document.getElementById('atomic-tab').click(); document.getElementById('composite-tab').click(); } }")
            self.assertEqual((await self.paths(page)).count('/api/composite/build'), 1)
            await page.evaluate('window.__releaseRequest()')
            await self.idle(page, 'composite')
            self.assertTrue(await page.locator('#composite-schema-results').is_visible())
        self.run_page(exercise, delayed='/api/composite/build')

    def test_reload_during_pending_first_selection_retries_without_a_snapshot(self):
        async def exercise(page, _url):
            await page.wait_for_function("typeof window.__releaseRequest === 'function'", timeout=10000)
            await page.reload()
            await page.wait_for_function("typeof window.__releaseRequest === 'function'", timeout=10000)
            await page.evaluate('window.__releaseRequest()')
            await self.idle(page, 'atomic')
            self.assertTrue(await page.locator('#atomic-problem-card').is_visible())
            self.assertEqual(await page.locator('#atomic-problem-text').inner_text(), 'bare')
            self.assertEqual((await self.paths(page)).count('/api/template'), 1)
        self.run_page(exercise, delayed='/api/template')

    def test_logo_during_pending_build_suppresses_both_views_until_fresh_visit(self):
        async def exercise(page, url):
            await self.idle(page, 'atomic')
            await page.locator('#composite-tab').click()
            await page.wait_for_function("typeof window.__releaseRequest === 'function'", timeout=10000)
            # Hold the brand's navigation behind the real queued storage promise,
            # so a late worker response has a chance to mutate the old document.
            await page.evaluate("""async () => {
              const state = await import('./view-state.js');
              const original = IDBDatabase.prototype.transaction;
              IDBDatabase.prototype.transaction = function(...args) {
                const tx = original.apply(this, args);
                if (args[1] === 'readwrite') {
                  const add = tx.addEventListener.bind(tx);
                  Object.defineProperty(tx, 'oncomplete', {set(fn) { add('complete', () => { window.__releaseReset = fn; }); }});
                }
                return tx;
              };
              await state.flushViewState();
              document.querySelector('.brand').click();
            }""")
            await page.wait_for_function("typeof window.__releaseReset === 'function'", timeout=10000)
            await page.evaluate('window.__releaseRequest()')
            await page.wait_for_function("!document.getElementById('composite-structure-controls').disabled", timeout=10000)
            self.assertTrue(await page.locator('#composite-schema-results').is_hidden(), 'A pending build rendered after the brand reset')
            await page.evaluate('window.__releaseReset()')
            await page.wait_for_url(url)
            await self.idle(page, 'atomic')
            self.assertTrue(await page.locator('#atomic-problem-card').is_hidden())
            await page.locator('#composite-tab').click()
            await self.idle(page, 'composite')
            self.assertTrue(await page.locator('#composite-schema-results').is_hidden())
            await page.reload()
            await self.idle(page, 'composite')
            self.assertTrue(await page.locator('#composite-schema-results').is_hidden())
            await page.locator('#atomic-tab').click()
            await self.idle(page, 'atomic')
            self.assertTrue(await page.locator('#atomic-problem-card').is_hidden())
            self.assertNotIn('/api/template', await self.paths(page))
            self.assertNotIn('/api/composite/build', await self.paths(page))
            await page.locator('#atomic-generate-random').click()
            await self.idle(page, 'atomic')
            self.assertTrue(await page.locator('#atomic-problem-card').is_visible())
            await page.goto(url)
            await self.idle(page, 'atomic')
            self.assertTrue(await page.locator('#atomic-problem-card').is_visible())
        self.run_page(exercise, delayed='/api/composite/build')
