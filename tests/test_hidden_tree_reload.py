"""A tree restored behind the atomic tab centers when it becomes visible."""
import asyncio
import os
import unittest

from support import HAS_PLAYWRIGHT, ROOT, static_origin


@unittest.skipUnless(HAS_PLAYWRIGHT, 'Requires server Chromium')
class HiddenTreeReloadTests(unittest.TestCase):
    def test_hidden_reload_centers_root_once_without_resetting_manual_pan(self):
        from playwright.async_api import async_playwright
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.cache/ms-playwright'))

        async def exercise(url):
            async with async_playwright() as engine:
                browser = await engine.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(viewport={'width': 1280, 'height': 900})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))

                    async def idle(view):
                        await page.wait_for_function("view => !document.getElementById(view === 'atomic' ? 'atomic-catalogue-controls' : 'composite-structure-controls').disabled && document.getElementById(view + '-status').hidden", arg=view, timeout=180000)

                    async def geometry():
                        return await page.evaluate('''() => {
                          const viewport = document.getElementById('composite-tree-viewport');
                          const root = document.querySelector('#composite-tree .tree-root').getBoundingClientRect();
                          const frame = viewport.getBoundingClientRect();
                          return {left: root.left, right: root.right, top: root.top, bottom: root.bottom,
                            frameLeft: frame.left + viewport.clientLeft, frameTop: frame.top + viewport.clientTop,
                            width: viewport.clientWidth, height: viewport.clientHeight,
                            scrollLeft: viewport.scrollLeft, scrollTop: viewport.scrollTop,
                            scrollWidth: viewport.scrollWidth};
                        }''')

                    await page.goto(url)
                    await idle('atomic')
                    await page.locator('#composite-tab').click()
                    await page.locator('#composite-depth').fill('4')
                    await page.locator('#composite-width').fill('16')
                    await page.locator('#composite-structure-seed-mode').check()
                    await page.locator('#composite-structure-seed').fill('42')
                    await page.locator('#composite-structure-random').click()
                    await idle('composite')
                    before = await geometry()
                    self.assertGreater(before['scrollWidth'], 2 * before['width'])
                    self.assertGreater(before['scrollLeft'], 0)
                    await page.evaluate("async () => (await import('./view-state.js')).flushViewState()")
                    await page.locator('#atomic-tab').click()
                    await page.reload()
                    await idle('atomic')
                    await idle('composite')
                    self.assertTrue(await page.locator('#composite-panel').is_hidden())
                    self.assertEqual(await page.locator('#composite-tree .tree-root').count(), 1)
                    await page.locator('#composite-tab').click()
                    restored = await geometry()
                    self.assertGreaterEqual(restored['left'], restored['frameLeft'] - 1, restored)
                    self.assertLessEqual(restored['right'], restored['frameLeft'] + restored['width'] + 1, restored)
                    self.assertGreaterEqual(restored['top'], restored['frameTop'] - 1, restored)
                    self.assertLessEqual(restored['bottom'], restored['frameTop'] + restored['height'] + 1, restored)
                    self.assertAlmostEqual((restored['left'] + restored['right']) / 2,
                                           restored['frameLeft'] + restored['width'] / 2, delta=1)
                    await page.evaluate('''() => {
                      const viewport = document.getElementById('composite-tree-viewport');
                      viewport.scrollLeft += 347; viewport.scrollTop = 243;
                    }''')
                    manual = await geometry()
                    self.assertGreater(manual['scrollTop'], 0)
                    await page.locator('#atomic-tab').click()
                    await page.locator('#composite-tab').click()
                    await page.locator('#composite-parameter-seed-mode').check()
                    await page.locator('#composite-parameter-seed').fill('17')
                    await page.locator('#composite-parameter-random').click()
                    await idle('composite')
                    filled = await geometry()
                    self.assertAlmostEqual(filled['scrollLeft'], manual['scrollLeft'], delta=1)
                    self.assertAlmostEqual(filled['scrollTop'], manual['scrollTop'], delta=1)
                    await page.locator('#composite-reset-parameters').click()
                    reset = await geometry()
                    self.assertAlmostEqual(reset['scrollLeft'], manual['scrollLeft'], delta=1)
                    self.assertAlmostEqual(reset['scrollTop'], manual['scrollTop'], delta=1)
                    self.assertFalse(errors, errors)
                finally:
                    await browser.close()
        with static_origin() as server:
            asyncio.run(exercise(server.url))
