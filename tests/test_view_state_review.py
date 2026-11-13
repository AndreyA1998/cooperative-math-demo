"""Independent reload lifecycle tests with a small deterministic transport."""
import asyncio
import os
import unittest
from support import HAS_PLAYWRIGHT, ROOT, static_origin

TRANSPORT = r'''
export function hideIdleRuntime() {}
const id = 'algebra/test/1';
const presentation = (value) => ({segments:[{kind:'text',text:value}],inputs:[]});
export async function request(method,path,query='',body=null) {
  window.__reviewPaths ??= []; window.__reviewPaths.push(path);
  const fields = new URLSearchParams(query), input = body && JSON.parse(body);
  let data;
  if(path.endsWith('/catalogue')) data={problems:[{id,subject:'algebra',split:'test'}]};
  else if(path.endsWith('/template')) data={presentation:presentation('bare'),problem_template:'bare'};
  else if(path.endsWith('/generate')) data={seed:fields.get('seed'),answer:'answer '+fields.get('seed'),problem:'filled '+fields.get('seed'),presentation:presentation('filled '+fields.get('seed'))};
  else if(path.endsWith('/build')) data={seed:input.seed,nodes:[{node_id:'n1',number:1,source_id:id,children:[],bindings:[],profile:{parameter_names:[]}}],root_id:'n1',depth:1,actual_width:1,requested_width:1,problem_template:'schema '+input.seed};
  else if(path.endsWith('/presentation')) data={nodes:[{node_id:'n1',number:1,source_id:id,kind:'external',inputs:[],incoming:[],segments:[{kind:'text',text:input.schema.problem_template}],answer:null}]};
  else throw Error('Unexpected review request '+path);
  return {data,raw:JSON.stringify(data)};
}
'''
DELAYED_STORAGE = r'''
export {saveViewState,flushViewState,readCatalogueCache,saveCatalogueCache,resetViewState} from './view-state.js?storage';
import {readViewState as read} from './view-state.js?storage';
export async function readViewState(view) {
  const saved=await read(view);
  if(view==='composite' && saved) await new Promise(resolve=>window.__releaseRestore=resolve);
  return saved;
}
'''

@unittest.skipUnless(HAS_PLAYWRIGHT, 'Requires server Chromium')
class ViewStateReviewTests(unittest.TestCase):
    def run_page(self, exercise, *, delayed=False):
        from playwright.async_api import async_playwright
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.cache/ms-playwright'))
        async def run(url):
            async with async_playwright() as engine:
                browser=await engine.chromium.launch(headless=True)
                try:
                    context=await browser.new_context()
                    page=await context.new_page()
                    await page.route('**/transport.js',lambda route:route.fulfill(content_type='text/javascript',body=TRANSPORT))
                    await page.route('**/math-renderer.js',lambda route:route.fulfill(content_type='text/javascript',body='export const MathPresentation={render:async(node,parts)=>{node.textContent=parts.map(p=>p.text).join("");return true;}};'))
                    if delayed:
                        await page.route('**/view-state.js',lambda route:route.fulfill(content_type='text/javascript',body=DELAYED_STORAGE))
                    await page.goto(url)
                    await page.wait_for_function("!document.getElementById('atomic-catalogue-controls').disabled")
                    await exercise(page)
                finally: await browser.close()
        with static_origin() as server: asyncio.run(run(server.url))

    def test_reload_preserves_unsubmitted_seed_draft_and_previous_answer(self):
        async def exercise(page):
            await page.locator('#atomic-problem-id').select_option('algebra/test/1')
            await page.wait_for_function("document.getElementById('atomic-status').hidden")
            await page.locator('#atomic-seed-mode').check()
            await page.locator('#atomic-seed').fill('42')
            await page.locator('#atomic-generate').click()
            await page.wait_for_function("document.getElementById('atomic-answer-value').textContent==='answer 42'")
            await page.locator('#atomic-seed').fill('7')
            await page.evaluate("async()=>await (await import('./view-state.js')).flushViewState()")
            await page.reload()
            await page.wait_for_function("document.getElementById('atomic-answer-value').textContent==='answer 42'")
            self.assertEqual(await page.locator('#atomic-seed').input_value(),'7')
        self.run_page(exercise)

    def test_pending_tree_restore_disables_new_build_until_saved_state_is_known(self):
        async def exercise(page):
            await page.locator('#composite-tab').click()
            await page.locator('#composite-structure-seed-mode').check()
            await page.locator('#composite-structure-seed').fill('42')
            await page.locator('#composite-structure-random').click()
            await page.wait_for_function("!document.getElementById('composite-schema-results').hidden && document.getElementById('composite-status').hidden")
            await page.evaluate("async()=>await (await import('./view-state.js')).flushViewState()")
            await page.reload()
            await page.wait_for_function("typeof window.__releaseRestore==='function'")
            self.assertTrue(await page.locator('#composite-structure-controls').evaluate('(node)=>node.disabled'),
                            'New build is enabled while an older saved schema can still restore over it')
            await page.evaluate('window.__releaseRestore()')
        self.run_page(exercise,delayed=True)

    def test_brand_clears_both_saved_views_and_returns_to_empty_atomic_page(self):
        async def exercise(page):
            home = page.url.split("?", 1)[0].split("#", 1)[0]
            await page.locator('#atomic-problem-id').select_option('algebra/test/1')
            await page.wait_for_function("document.getElementById('atomic-status').hidden")
            await page.locator('#atomic-seed-mode').check()
            await page.locator('#atomic-seed').fill('42')
            await page.locator('#atomic-generate').click()
            await page.wait_for_function("document.getElementById('atomic-answer-value').textContent==='answer 42'")
            await page.locator('#composite-tab').click()
            await page.locator('#composite-structure-seed-mode').check()
            await page.locator('#composite-structure-seed').fill('7')
            await page.locator('#composite-structure-random').click()
            await page.wait_for_function("!document.getElementById('composite-schema-results').hidden && document.getElementById('composite-status').hidden")
            old_tab = await page.evaluate("sessionStorage.getItem('math-demo-tab')")
            await page.locator('.brand').click()
            await page.wait_for_url(home, timeout=10000)
            await page.wait_for_function("!document.getElementById('atomic-catalogue-controls').disabled")
            self.assertTrue(await page.locator('#atomic-problem-card').is_hidden())
            self.assertTrue(await page.locator('#composite-schema-results').is_hidden())
            self.assertEqual(await page.locator('#atomic-tab').get_attribute('aria-selected'), 'true')
            self.assertEqual(await page.locator('#atomic-subject').input_value(), 'algebra')
            for name in ('atomic-seed-mode', 'composite-structure-seed-mode', 'composite-parameter-seed-mode'):
                self.assertFalse(await page.locator('#' + name).is_checked())
            keys = await page.evaluate("""async () => {
              const db = await new Promise(resolve => {const r=indexedDB.open('math-demo-view-state',1);r.onsuccess=()=>resolve(r.result);});
              return await new Promise(resolve => {const r=db.transaction('views').objectStore('views').getAllKeys();r.onsuccess=()=>resolve(r.result);});
            }""")
            self.assertNotIn(old_tab + ':atomic', keys)
            self.assertNotIn(old_tab + ':composite', keys)
            self.assertIn('catalogue', keys)
            self.assertNotIn('/api/catalogue', await page.evaluate('window.__reviewPaths ?? []'))
            await page.reload()
            await page.wait_for_function("!document.getElementById('atomic-catalogue-controls').disabled")
            self.assertTrue(await page.locator('#atomic-problem-card').is_hidden())
            self.assertTrue(await page.locator('#composite-schema-results').is_hidden())
        self.run_page(exercise)

    def test_tabs_keep_separate_exact_json_snapshots(self):
        async def exercise(page):
            # The small document isolates storage from mathematical presentation.
            url=page.url+'__renderer_test__.html'
            await page.goto(url)
            first='{"coefficient":9007199254740993,"seed":18446744073709551615,"value":"0011"}'
            second='{"coefficient":-9007199254740993,"seed":0,"value":"0.050"}'
            async def save(target, raw):
                return await target.evaluate("async raw=>{const s=await import('./view-state.js');await s.saveViewState('composite',{schema:raw,parameterSeed:'18446744073709551615'});await s.flushViewState();return sessionStorage.getItem('math-demo-tab');}",raw)
            first_tab=await save(page,first)
            other=await page.context.new_page()
            await other.goto(url)
            second_tab=await save(other,second)
            self.assertNotEqual(first_tab,second_tab)
            await page.reload();await other.reload()
            async def read(target):
                return await target.evaluate("async()=>await (await import('./view-state.js')).readViewState('composite')")
            self.assertEqual(await read(page),{'schema':first,'parameterSeed':'18446744073709551615'})
            self.assertEqual(await read(other),{'schema':second,'parameterSeed':'18446744073709551615'})
            await other.close()
        self.run_page(exercise)
