"""Real Pyodide covers first activation, restore, and preloaded empty logo resets."""
import asyncio
import os
import unittest

from support import HAS_PLAYWRIGHT, ROOT, static_origin


@unittest.skipUnless(HAS_PLAYWRIGHT, 'Requires server Chromium')
class StartupPreloadTests(unittest.TestCase):
    def exercise_cached_visit(self, navigation):
        from playwright.async_api import async_playwright
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.cache/ms-playwright'))

        async def exercise(url):
            async with async_playwright() as engine:
                browser = await engine.chromium.launch(headless=True)
                context = await browser.new_context(viewport={'width': 1280, 'height': 900})
                await context.add_init_script('''
                  window.__startup = {workers: 0, ready: 0, paths: []};
                  const NativeWorker = window.Worker;
                  window.Worker = new Proxy(NativeWorker, {
                    construct(Target, args) {
                      const worker = new Target(...args);
                      window.__startup.workers++;
                      worker.addEventListener('message', ({data}) => {
                        if (data.type === 'ready') window.__startup.ready++;
                      });
                      return worker;
                    }
                  });
                  const postMessage = NativeWorker.prototype.postMessage;
                  NativeWorker.prototype.postMessage = function(message, ...rest) {
                    window.__startup.paths.push(message.path);
                    return postMessage.call(this, message, ...rest);
                  };
                ''')
                page = await context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))

                async def idle():
                    await page.wait_for_function('''() =>
                      !document.getElementById('atomic-catalogue-controls').disabled &&
                      document.getElementById('atomic-status').hidden
                    ''', timeout=180000)

                async def catalogue_record(key='catalogue'):
                    return await page.evaluate('''async key => {
                      const db = await new Promise((resolve, reject) => {
                        const request = indexedDB.open('math-demo-view-state', 1);
                        request.onsuccess = () => resolve(request.result);
                        request.onerror = () => reject(request.error);
                      });
                      try {
                        return await new Promise((resolve, reject) => {
                          const request = db.transaction('views').objectStore('views').get(key);
                          request.onsuccess = () => resolve(request.result);
                          request.onerror = () => reject(request.error);
                        });
                      } finally { db.close(); }
                    }''', key)

                try:
                    await page.goto(url)
                    await idle()
                    await page.wait_for_function('window.__startup.ready === 1', timeout=180000)
                    self.assertEqual(await page.evaluate('window.__startup.workers'), 1)
                    self.assertEqual(await page.evaluate('window.__startup.paths'), ['/api/catalogue', '/api/template'])
                    self.assertTrue(await page.locator('#atomic-problem-card').is_visible())
                    self.assertEqual(await page.locator('#atomic-answer-value').inner_text(), '—')
                    self.assertTrue(await page.locator('#composite-schema-results').is_hidden())
                    atomic_id = await page.locator('#atomic-problem-id').input_value()
                    cached = await catalogue_record()
                    self.assertTrue(cached['problems'])
                    await page.locator('#composite-tab').click()
                    await page.wait_for_function("!document.getElementById('composite-structure-controls').disabled && document.getElementById('composite-status').hidden", timeout=180000)
                    self.assertTrue(await page.locator('#composite-schema-results').is_visible())
                    self.assertEqual(await page.locator('#composite-root-answer').inner_text(), '—')
                    self.assertEqual((await page.evaluate('window.__startup.paths')).count('/api/composite/build'), 1)
                    await page.evaluate("async () => (await import('./view-state.js')).flushViewState()")
                    tab = await page.evaluate("sessionStorage.getItem('math-demo-tab')")
                    schema = (await catalogue_record(tab + ':composite'))['state']['schema']
                    await page.reload()
                    await idle()
                    await page.wait_for_function("!document.getElementById('composite-structure-controls').disabled && document.getElementById('composite-status').hidden", timeout=180000)
                    self.assertEqual(await page.evaluate("async () => (await (await import('./view-state.js')).readViewState('composite')).schema"), schema)
                    self.assertEqual(await page.locator('#atomic-problem-id').input_value(), atomic_id)
                    self.assertEqual(await page.locator('#atomic-answer-value').inner_text(), '—')
                    paths = await page.evaluate('window.__startup.paths')
                    self.assertNotIn('/api/catalogue', paths)
                    self.assertNotIn('/api/composite/build', paths)
                    self.assertNotIn('/api/generate', paths)
                    self.assertNotIn('/api/composite/variant', paths)
                    await page.locator('#composite-structure-seed-mode').check()
                    await page.locator('#composite-parameter-seed-mode').check()
                    await page.locator('#atomic-tab').click()
                    await page.locator('#atomic-seed-mode').check()
                    async with page.expect_navigation():
                        await page.locator('a.brand').click()
                    await idle()
                    if navigation == 'reload':
                        await page.reload()
                    await idle()
                    self.assertEqual(await page.evaluate('window.__startup.workers'), 1,
                                     'A cached empty visit left the Python worker unstarted')
                    await page.wait_for_function('window.__startup.ready === 1', timeout=180000)
                    self.assertEqual(await page.evaluate('window.__startup.paths'), [],
                                     'Preparing the worker rebuilt the cached catalogue or generated a task')
                    self.assertEqual(await catalogue_record(), cached)
                    self.assertTrue(await page.locator('.runtime-banner').is_hidden())
                    self.assertTrue(await page.locator('#atomic-problem-card').is_hidden())
                    self.assertTrue(await page.locator('#composite-schema-results').is_hidden())
                    self.assertEqual(await page.locator('#atomic-problem-id').input_value(), '')
                    await page.locator('#composite-tab').click()
                    await page.wait_for_function("!document.getElementById('composite-structure-controls').disabled", timeout=180000)
                    self.assertTrue(await page.locator('#composite-schema-results').is_hidden())
                    await page.locator('#atomic-tab').click()
                    for prefix in ('atomic', 'composite-structure', 'composite-parameter'):
                        self.assertFalse(await page.locator('#' + prefix + '-seed-mode').is_checked())
                    await page.locator('#atomic-generate-random').click()
                    await idle()
                    self.assertTrue(await page.locator('#atomic-problem-card').is_visible())
                    self.assertEqual(await page.evaluate('window.__startup.workers'), 1,
                                     'The first explicit task discarded the prepared worker')
                    self.assertEqual(await page.evaluate('window.__startup.ready'), 1)
                    self.assertEqual(await page.evaluate('window.__startup.paths'), ['/api/template'])
                    self.assertFalse(errors, errors)
                finally:
                    await browser.close()

        with static_origin() as server:
            asyncio.run(exercise(server.url))

    def test_first_activation_restore_and_logo_reset_reload_keep_runtime_prepared(self):
        self.exercise_cached_visit('reload')

    def test_logo_reset_prepares_runtime_before_task_selection(self):
        self.exercise_cached_visit('logo')
