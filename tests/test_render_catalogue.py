"""Every native bare pattern and three seeded variants render in real KaTeX."""
import asyncio
import json
import os
import unittest
from support import HAS_PLAYWRIGHT, ROOT, ensure_runtime, static_origin
ensure_runtime()
from math_demo.presentation import atomic_presentation
from template_dataset.registry import generate,registry


@unittest.skipUnless(HAS_PLAYWRIGHT, 'Requires server Chromium and pinned KaTeX CDN')
class CatalogueRenderingTests(unittest.TestCase):
    def test_all_patterns_and_three_variants_have_no_tex_fallback(self):
        from playwright.async_api import async_playwright
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.cache/ms-playwright'))
        records=[]
        for source in sorted(registry()):
            variants=[('bare',None)]+[(str(seed),generate(source,seed)['parameters']) for seed in (0,17,2**64-1)]
            for mode,params in variants:
                shown=atomic_presentation(source,params)
                self.assertEqual(shown['scope'],'native-fields',source+' '+mode)
                records.append({'id':source,'mode':mode,'segments':shown['segments']})
        self.assertEqual(len(records),4286*4)
        async def exercise(url):
            async with async_playwright() as engine:
                browser=await engine.chromium.launch(headless=True)
                try:
                    page=await browser.new_page(viewport={'width':1200,'height':900})
                    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    await page.goto(url+'__renderer_test__.html')
                    await page.evaluate(r'''async()=>{
                        window.catalogueTarget=document.createElement('div');
                        catalogueTarget.style.cssText='width:960px;position:absolute;left:-20000px';document.body.append(catalogueTarget);
                        window.catalogueRenderer=(await import('./math-renderer.js')).MathPresentation;
                        if(!await catalogueRenderer.render(catalogueTarget,[{kind:'text',text:'$x^2$'}])||!window.katex)throw Error('Pinned KaTeX failed to load');
                        window.catalogueErrors=[];
                        const original=katex.render;
                        katex.render=(source,node,options)=>{try{const value=original(source,node,options);const error=node.querySelector('.katex-error');if(error)catalogueErrors.push({source,error:error.title||error.textContent});return value;}catch(error){catalogueErrors.push({source,error:String(error)});throw error;}};
                    }''')
                    failures=[];fragments=0
                    for start in range(0,len(records),200):
                        results=await page.evaluate(r'''async rows=>{
                            const results=[];
                            for(const row of rows){
                                catalogueErrors.length=0;let rendered=false,exception=null;
                                try{rendered=await catalogueRenderer.render(catalogueTarget,row.segments);}catch(error){exception=String(error);}
                                const fragments=[...catalogueTarget.querySelectorAll('.math-fragment')];
                                const walker=document.createTreeWalker(catalogueTarget,NodeFilter.SHOW_TEXT);
                                let node,outside='';while(node=walker.nextNode())if(!node.parentElement.closest('.math-fragment'))outside+=node.textContent;
                                const raw=outside.match(/\\(?:begin|end|frac|dfrac|tfrac|sqrt|left|right|sum|prod|text|overline|angle|cdot|times|pi|boxed|displaystyle)\b|\[\/?asy\]/g)||[];
                                const failed=fragments.filter(node=>node.dataset.rendered!=='true');
                                results.push({id:row.id,mode:row.mode,fragments:fragments.length,ok:rendered&&!failed.length&&!raw.length&&!exception,
                                    ...(raw.length?{raw:[...new Set(raw)],sample:outside.slice(0,300)}:{}),
                                    ...(catalogueErrors.length?{errors:catalogueErrors.map(error=>({error:error.error,source:error.source.slice(0,300)}))}:{}),
                                    ...(exception?{exception}:{}),});
                            }
                            return results;
                        }''',records[start:start+200])
                        for result in results:
                            fragments+=result['fragments']
                            if not result['ok']:failures.append(result)
                    self.assertFalse(errors,errors)
                    self.assertFalse(failures,json.dumps({'failed_conditions':len(failures),'examples':failures[:20]},ensure_ascii=False))
                    print(f'KaTeX catalogue: {len(records)} conditions, {fragments} formula fragments, no fallback or raw TeX blocks.')
                finally:await browser.close()
        with static_origin() as server:asyncio.run(exercise(server.url))
