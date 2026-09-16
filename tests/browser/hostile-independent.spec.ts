import { test, expect } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { inputPath } from './paths';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const supplied = process.env.LIBRARY_HOSTILE_EVIDENCE;
const dir = supplied ? inputPath(supplied) : '';
test.beforeEach(() => { test.skip(!supplied, 'Set LIBRARY_HOSTILE_EVIDENCE to the independently generated evidence directory.'); });
for(const format of ['single.html','bundle/index.html'])test(`independent offline hostile text stays literal in ${format}`,async ({page}, testInfo) =>{
 const verification=JSON.parse(await readFile(resolve(dir,'verification.json'),'utf8'));
 const requests:string[]=[];const errors:string[]=[];
 page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(resolve(dir,format)).href);
 await expect(page.locator('body')).toContainText(verification.payload);
 expect(await page.evaluate(()=>Object.prototype.hasOwnProperty.call(window,'ATTACK_RAN'))).toBe(false);
 expect(await page.locator('img[src*="attacker.invalid"],script[src*="attacker.invalid"],[onerror]').count()).toBe(0);
 expect(requests).toEqual([]);expect(errors).toEqual([]);
 const name=format.startsWith('bundle')?'bundle':'single';
 await page.screenshot({path:testInfo.outputPath(`independent-${name}-desktop.png`),fullPage:true});
  await page.setViewportSize({width:320,height:900});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(320);
 const textOverflow=await page.locator('[data-language="target"]').filter({hasText:'ATTACK_RAN'}).evaluate(node=>{
   const e=node as HTMLElement;const ancestors=[];let x:HTMLElement|null=e;
   while(x&&ancestors.length<5){const style=getComputedStyle(x);const before=x.scrollLeft;x.scrollLeft=10000;const reachable=x.scrollLeft;x.scrollLeft=before;ancestors.push({tag:x.tagName,classes:x.className,clientWidth:x.clientWidth,scrollWidth:x.scrollWidth,overflowX:style.overflowX,overflowWrap:style.overflowWrap,wordBreak:style.wordBreak,scrollReachable:reachable});x=x.parentElement;}
   return ancestors;
 });
 expect(textOverflow[0].scrollWidth,'Literal long tokens must not be clipped within the text container').toBeLessThanOrEqual(textOverflow[0].clientWidth);
 await page.screenshot({path:testInfo.outputPath(`independent-${name}-320.png`),fullPage:true});
 await writeFile(testInfo.outputPath(`independent-${name}-facts.json`),JSON.stringify({reviewer:'/root/web_ui',format,sha256:createHash('sha256').update(await readFile(resolve(dir,format))).digest('hex'),literal_payload_exact:true,attack_ran:false,outbound:requests,errors,viewport320_no_overflow:true,textOverflow},null,2));
});
