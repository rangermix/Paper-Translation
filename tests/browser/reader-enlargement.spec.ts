import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { inputPath } from './paths';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { writeFile,readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const supplied = process.env.LIBRARY_ENLARGEMENT_EVIDENCE;
const folder = supplied ? inputPath(supplied) : '';
test.beforeEach(() => { test.skip(!supplied, 'Set LIBRARY_ENLARGEMENT_EVIDENCE to the independently generated evidence directory.'); });
for(const template of ['reader-v1','reader-v2'])test(`literal font enlargement keyboard and long code remain accessible in ${template}`,async ({page,context}, testInfo) =>{
  const file=resolve(folder,`${template}.html`);await context.setOffline(true);
  await page.setViewportSize({width:320,height:900});await page.goto(pathToFileURL(file).href);
  const originalFont=await page.locator('body').evaluate(e=>getComputedStyle(e).fontSize);
  for(let i=0;i<6;i++)await page.locator('[data-action="larger"]').click();
  expect(await page.locator('body').evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThan(parseFloat(originalFont));
  const controls=await page.locator('.toolbar button').evaluateAll(nodes=>nodes.map(e=>{const r=e.getBoundingClientRect();return {label:e.textContent,visible:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight};}));
  expect(controls.length).toBeGreaterThan(0);expect(controls.every(c=>c.visible)).toBe(true);
  const font=await page.locator('body').evaluate(e=>getComputedStyle(e).fontSize);
  const documentWidth=await page.evaluate(()=>document.documentElement.scrollWidth);expect(documentWidth).toBe(320);
  // Start a literal Tab path from an unfocused body; the browser moves and scrolls focus itself.
  await page.evaluate(()=>{(document.activeElement as HTMLElement)?.blur();window.scrollTo(0,0);});
  const focus=[];
  for(let i=0;i<7;i++){
    await page.keyboard.press('Tab');
    await expect.poll(()=>page.evaluate(()=>{const r=document.activeElement!.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;})).toBe(true);
    const item=await page.evaluate(()=>{const e=document.activeElement as HTMLElement;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return {tag:e.tagName,text:e.textContent,top:r.top,bottom:r.bottom,left:r.left,right:r.right,outlineStyle:s.outlineStyle,outlineWidth:s.outlineWidth};});
    expect(item.tag).not.toBe('BODY');expect(item.left).toBeGreaterThanOrEqual(0);expect(item.right).toBeLessThanOrEqual(320);expect(item.top).toBeGreaterThanOrEqual(0);expect(item.bottom).toBeLessThanOrEqual(900);expect(item.outlineStyle).not.toBe('none');focus.push(item);
  }
  const code=await page.locator('#b-long-code pre').evaluate(e=>{e.scrollLeft=e.scrollWidth;return {width:e.clientWidth,scrollWidth:e.scrollWidth,reached:e.scrollLeft};});
  expect(code.reached).toBeGreaterThan(0);
  const ordinary=await page.locator('[data-language]').evaluateAll(nodes=>nodes.filter(e=>!e.closest('table')).map(e=>({id:e.closest('[data-block-id]')?.getAttribute('data-block-id'),width:e.clientWidth,scroll:e.scrollWidth})).filter(x=>x.scroll>x.width+1));
  expect(ordinary).toEqual([]);
  await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:testInfo.outputPath(`independent-${template}-font30.png`),fullPage:true});
  await page.screenshot({path:testInfo.outputPath(`independent-${template}-font30-viewport.png`)});
  await writeFile(testInfo.outputPath(`independent-${template}-font30.json`),JSON.stringify({template,file,sha256:createHash('sha256').update(await readFile(file)).digest('hex'),originalFont,font,viewport:320,documentWidth,controls,focus,code,clipped_text:ordinary,provider_calls:0},null,2));
});
