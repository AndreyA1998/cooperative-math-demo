"""Actual page reloads preserve exact programs, and fresh visits select a new bare template."""
import asyncio
import os
import unittest
from support import HAS_PLAYWRIGHT, ROOT, static_origin


@unittest.skipUnless(HAS_PLAYWRIGHT, 'Requires server Chromium')
class ReloadStateTests(unittest.TestCase):
    def test_reload_preserves_both_views_without_catalogue_or_tree_rebuild(self):
        from playwright.async_api import async_playwright
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.cache/ms-playwright'))

        async def exercise(url):
            async with async_playwright() as engine:
                browser = await engine.chromium.launch(headless=True)
                context = await browser.new_context(viewport={'width': 1280, 'height': 900})
                await context.add_init_script('''
                  window.__apiPaths = [];
                  const original = Worker.prototype.postMessage;
                  Worker.prototype.postMessage = function(message, ...rest) {
                    window.__apiPaths.push(message.path);
                    return original.call(this, message, ...rest);
                  };
                ''')
                page = await context.new_page()
                errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                async def idle(kind):
                    await page.wait_for_function("k => !document.getElementById(k === 'atomic' ? 'atomic-catalogue-controls' : 'composite-structure-controls').disabled && document.getElementById(k + '-status').hidden", arg=kind, timeout=180000)
                async def flush():
                    await page.evaluate("async () => (await import('./view-state.js')).flushViewState()")
                try:
                    await page.goto(url + '?id=prealgebra/test/11&seed=42')
                    await idle('atomic')
                    self.assertTrue(await page.locator('#atomic-problem-card').is_visible())
                    self.assertEqual(await page.locator('#atomic-answer-value').inner_text(), '—')
                    self.assertEqual(await page.locator('#atomic-subject').input_value(), 'algebra')
                    self.assertFalse(await page.locator('#atomic-seed-mode').is_checked())
                    await page.locator('#atomic-split').select_option('train'); await idle('atomic')
                    await page.locator('#atomic-problem-id').select_option('algebra/train/1316'); await idle('atomic')
                    await page.locator('#atomic-seed-mode').check()
                    await page.locator('#atomic-seed').fill('0')
                    await page.locator('#atomic-generate').click(); await idle('atomic')
                    atomic = (await page.locator('#atomic-problem-text').inner_text(), await page.locator('#atomic-answer-value').inner_text())
                    await page.locator('#composite-tab').click()
                    await page.locator('#composite-structure-seed-mode').check()
                    await page.locator('#composite-structure-seed').fill('42')
                    await page.locator('#composite-structure-random').click(); await idle('composite')
                    await page.locator('#composite-parameter-seed-mode').check()
                    await page.locator('#composite-parameter-seed').fill('7')
                    await page.locator('#composite-parameter-random').click(); await idle('composite')
                    answer = await page.locator('#composite-root-answer').inner_text()
                    await page.locator('#composite-structure-seed').fill('99')
                    await page.locator('#composite-parameter-seed').fill('123')
                    await flush()
                    snapshot = await page.evaluate("async () => { const s=await import('./view-state.js'); const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('math-demo-view-state',1);r.onsuccess=()=>resolve(r.result);r.onerror=reject;}); return new Promise(resolve=>{const r=db.transaction('views').objectStore('views').get(sessionStorage.getItem('math-demo-tab')+':composite');r.onsuccess=()=>resolve(r.result.state.schema);}); }")
                    await page.reload()
                    await page.wait_for_function("() => !document.getElementById('composite-schema-results').hidden && document.getElementById('composite-root-answer').textContent !== '—'", timeout=180000)
                    await idle('composite'); await idle('atomic')
                    self.assertEqual(await page.locator('#composite-root-answer').inner_text(), answer)
                    self.assertTrue(await page.locator('#composite-parameter-seed-mode').is_checked())
                    self.assertEqual(await page.locator('#composite-parameter-seed').input_value(), '123')
                    self.assertEqual(await page.locator('#composite-structure-seed').input_value(), '99')
                    paths = await page.evaluate('window.__apiPaths')
                    self.assertNotIn('/api/catalogue', paths)
                    self.assertNotIn('/api/composite/build', paths)
                    await page.locator('#atomic-tab').click()
                    self.assertEqual((await page.locator('#atomic-problem-text').inner_text(), await page.locator('#atomic-answer-value').inner_text()), atomic)
                    await page.locator('#atomic-reset').click()
                    await page.locator('#composite-tab').click()
                    await page.locator('#composite-reset-parameters').click(); await flush()
                    await page.reload()
                    await page.wait_for_function("() => !document.getElementById('composite-schema-results').hidden", timeout=180000)
                    await idle('composite'); await idle('atomic')
                    self.assertEqual(await page.locator('#composite-root-answer').inner_text(), '—')
                    restored = await page.evaluate("async () => (await (await import('./view-state.js')).readViewState('composite')).schema")
                    self.assertEqual(restored, snapshot, 'Reload reconstructed or rounded the saved schema')
                    await page.locator('#atomic-tab').click()
                    self.assertEqual(await page.locator('#atomic-answer-value').inner_text(), '—')
                    # A new navigation is a fresh visit, even in the same browser.
                    await page.goto(url); await idle('atomic')
                    self.assertTrue(await page.locator('#atomic-problem-card').is_visible())
                    self.assertEqual(await page.locator('#atomic-answer-value').inner_text(), '—')
                    self.assertTrue(await page.locator('#composite-schema-results').is_hidden())
                    self.assertEqual(await page.locator('#atomic-subject').input_value(), 'algebra')
                    self.assertNotIn('/api/catalogue', await page.evaluate('window.__apiPaths'))
                    self.assertFalse(errors, errors)
                finally:
                    await browser.close()
        with static_origin() as server:
            asyncio.run(exercise(server.url))
