import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { inputPath } from './paths';
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
const supplied = process.env.LIBRARY_COMPLETE_MATH_EVIDENCE;
const dir = supplied ? inputPath(supplied) : '';
test.beforeEach(() => { test.skip(!supplied, 'Set LIBRARY_COMPLETE_MATH_EVIDENCE to the independently generated evidence directory.'); });
for(const format of ['single.html','bundle/index.html'])test(`all 86 reviewed mathematical source references are individually reachable in ${format}`,async ({page}, testInfo) =>{
 test.setTimeout(180000);
 const response=JSON.parse(await readFile(resolve(dir,'response.json'),'utf8'));const source=response.source;
 const refs=source.blocks.flatMap((b:any)=>b.source_inline.filter((n:any)=>n.type==='xref'&&n.target_block_id.startsWith('math-annotation-')).map((n:any)=>({owner:b.id,...n})));
 expect(refs).toHaveLength(86);const outbound:string[]=[];const errors:string[]=[];page.on('request',r=>{if(/^https?:/.test(r.url()))outbound.push(r.url());});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(resolve(dir,format)).href);await expect(page.locator('body')).toContainText('DRAFT');await page.setViewportSize({width:320,height:900});
 const order=await page.locator('[data-block-id]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-block-id')));const facts=[];
 for(const ref of refs){
  const target=page.locator(`[data-block-id="${ref.target_block_id}"]`);const link=page.locator(`[data-block-id="${ref.owner}"] a[href="#b-${ref.target_block_id}"]`);
  await expect(link).toHaveCount(1);await expect(target).toHaveCount(1);expect(order.indexOf(ref.target_block_id)).toBeGreaterThan(order.indexOf(ref.owner));
  await link.click();await expect(page).toHaveURL(new RegExp(`#b-${ref.target_block_id}$`));await expect(target).toBeInViewport();
  expect(await target.locator('img').evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth>0)).toBe(true);
  await expect.poll(()=>target.locator('img').evaluate(img=>{const toolbar=document.querySelector('.toolbar')!;const position=getComputedStyle(toolbar).position;const minimum=position==='sticky'||position==='fixed'?Math.max(0,toolbar.getBoundingClientRect().bottom):0;return img.getBoundingClientRect().top>=minimum;})).toBe(true);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(320);facts.push({...ref,clicked:true,image_loaded:true,independent_root_once:true});
 }
 const name=format.startsWith('bundle')?'bundle':'single';await page.setViewportSize({width:1440,height:1060});
 for(const bid of ['b39','b63','b203']){const target=page.locator(`[data-block-id="${bid}"]`);await target.scrollIntoViewIfNeeded();await page.screenshot({path:testInfo.outputPath(`independent-${name}-${bid}-desktop.png`)});}
 await page.setViewportSize({width:320,height:900});for(const bid of ['b39','b63','b203']){const ref=refs.find((r:any)=>r.owner===bid);await page.locator(`[data-block-id="${bid}"] a[href="#b-${ref.target_block_id}"]`).click();await page.screenshot({path:testInfo.outputPath(`independent-${name}-${bid}-320.png`)});}
 expect(outbound).toEqual([]);expect(errors).toEqual([]);await writeFile(testInfo.outputPath(`independent-${name}-browser.json`),JSON.stringify({reviewer:'/root/web_ui',format,sha256:createHash('sha256').update(await readFile(resolve(dir,format))).digest('hex'),source_hash:response.source_hash,refs:facts,viewport320:true,outbound,errors,scope:'Actual original-pixel source reference navigation; DRAFT preview has no fabricated translation and preserves math as separate reachable roots, not inline typesetting.'},null,2));
});

test('focused math screenshots wait for real scrolling to settle',async ({page}, testInfo) =>{
 const response=JSON.parse(await readFile(resolve(dir,'response.json'),'utf8'));
 for(const format of ['single.html','bundle/index.html']){
  await page.goto(pathToFileURL(resolve(dir,format)).href);await page.setViewportSize({width:320,height:900});
  for(const bid of ['b39','b63','b203']){
   const block=response.source.blocks.find((b:any)=>b.id===bid);const ref=block.source_inline.find((n:any)=>n.type==='xref'&&n.target_block_id.startsWith('math-annotation-'));
   await page.locator(`[data-block-id="${bid}"] a[href="#b-${ref.target_block_id}"]`).click();
   const target=page.locator(`[data-block-id="${ref.target_block_id}"]`);await expect(target).toBeInViewport();
   const name=format.startsWith('bundle')?'bundle':'single';await target.screenshot({path:testInfo.outputPath(`independent-${name}-${bid}-math-close.png`)});
   await page.screenshot({path:testInfo.outputPath(`independent-${name}-${bid}-320-settled.png`)});
  }
 }
});

test('320px anchor reveals the original formula fully below the fixed toolbar',async ({page}, testInfo) =>{
 const response=JSON.parse(await readFile(resolve(dir,'response.json'),'utf8'));const block=response.source.blocks.find((b:any)=>b.id==='b63');const ref=block.source_inline.find((n:any)=>n.type==='xref'&&n.target_block_id.startsWith('math-annotation-'));
 await page.goto(pathToFileURL(resolve(dir,'single.html')).href);await page.setViewportSize({width:320,height:900});await page.locator(`[data-block-id="b63"] a[href="#b-${ref.target_block_id}"]`).click();
 const img=page.locator(`[data-block-id="${ref.target_block_id}"] img`);let previous:number|undefined;let stable=0;
 await expect.poll(async()=>{const top=(await img.boundingBox())!.y;stable=previous!==undefined&&Math.abs(previous-top)<.5?stable+1:0;previous=top;return stable;},{intervals:[100],timeout:5000}).toBeGreaterThanOrEqual(3);
 const imageBox=await img.boundingBox();const toolbarBox=await page.locator('.toolbar').boundingBox();expect(imageBox).not.toBeNull();expect(toolbarBox).not.toBeNull();
 await page.screenshot({path:testInfo.outputPath('independent-320-anchor-visibility.png')});await writeFile(testInfo.outputPath('independent-320-anchor-visibility.json'),JSON.stringify({source_hash:response.source_hash,target:ref.target_block_id,imageBox,toolbarBox,image_clears_toolbar:imageBox!.y>=toolbarBox!.y+toolbarBox!.height},null,2));
 expect(imageBox!.y).toBeGreaterThanOrEqual(toolbarBox!.y+toolbarBox!.height);
});

