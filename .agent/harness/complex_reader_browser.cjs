// M0 authored renderer check; no parser or paid-provider claim.
const {createRequire}=require('node:module');
const path=require('node:path'),fs=require('node:fs');
const {pathToFileURL}=require('node:url');
const {repoRoot:root,inputPath,outputDirectory}=require('./browser_paths.cjs');
const {chromium,expect}=createRequire(path.join(root,'src/apps/web/package.json'))('@playwright/test');
const directory=inputPath(process.env.COMPLEX_READER_INPUT||process.env.COMPLEX_READER_OUTPUT||'evidence/complex-reader-reviewed');
const output=outputDirectory('complex_reader_browser');
fs.mkdirSync(output,{recursive:true});
const ir=JSON.parse(fs.readFileSync(path.join(root,'fixtures/complex-reader/document-ir.json'),'utf8'));

async function main(){
  const browser=await chromium.launch({headless:true});
  const rows=[];
  try{
    for(const template of ['reader-v1','reader-v2'])for(const format of ['single','extracted-zip']){
      const ctx=await browser.newContext({viewport:{width:320,height:844}});
      const requests=[],errors=[];
      await ctx.route(/^https?:/,route=>{requests.push(route.request().url());return route.abort();});
      const page=await ctx.newPage();page.on('pageerror',e=>errors.push(String(e)));
      const target=format==='single'?template+'.html':template+'-extracted/index.html';
      await page.goto(pathToFileURL(path.join(directory,target)).href);
      await expect(page.locator('[data-block-id]')).toHaveCount(29);
      await expect(page.locator('aside.toc > ol > li')).toHaveCount(2);
      await expect(page.locator('aside.toc > ol > li').first().locator('ol > li > a')).toHaveAttribute('href','#b-deep-code');
      await expect(page.locator('aside.toc a[href="#b-title"]')).toHaveCount(0);
      await expect(page.locator('#b-regular-table td')).toHaveCount(4);
      await expect(page.locator('#b-merged-table td')).toHaveCount(7);
      await expect(page.locator('#b-merged-label')).toHaveAttribute('rowspan','2');
      await expect(page.locator('#b-merged-columns')).toHaveAttribute('colspan','2');
      await expect(page.locator('#b-long-code code')).toHaveText(ir.source_revision.blocks.find(b=>b.id==='long-code').raw_text,{useInnerText:false});
      await expect(page.locator('#b-cross-page [data-language="source"]')).toContainText('The second source location');
      await expect(page.locator('figure img')).toHaveJSProperty('naturalWidth',360);
      await expect(page.locator('a[download]')).toHaveCount(0);
      await page.keyboard.press('Tab');
      await expect(page.getByRole('button',{name:'双语',exact:true})).toBeFocused();
      const focus=await page.getByRole('button',{name:'双语',exact:true}).evaluate(e=>({style:getComputedStyle(e).outlineStyle,width:getComputedStyle(e).outlineWidth}));
      if(focus.style==='none'||parseFloat(focus.width)===0)throw Error('keyboard focus invisible '+JSON.stringify(focus));
      await page.keyboard.press('Tab');await page.keyboard.press('Enter');
      await expect(page.locator('#b-intro [data-language="target"]')).toBeHidden();
      await page.keyboard.press('Shift+Tab');await page.keyboard.press('Enter');
      await expect(page.locator('#b-intro [data-language="target"]')).toBeVisible();
      let reached=false;
      for(let i=0;i<30;i++){
        await page.keyboard.press('Tab');
        if(await page.locator('aside.toc a[href="#b-deep-code"]').evaluate(e=>e===document.activeElement)){reached=true;break;}
      }
      if(!reached)throw Error('nested ToC not reachable with Tab');
      await page.keyboard.press('Enter');await expect(page).toHaveURL(/#b-deep-code$/);
      await page.getByRole('button',{name:'增大字号',exact:true}).click();
      await page.getByRole('button',{name:'增大字号',exact:true}).click();
      const controls=await page.locator('.toolbar button').evaluateAll(elements=>elements.map(e=>{const r=e.getBoundingClientRect();return {text:e.textContent,x:r.x,right:r.right,width:r.width};}));
      if(controls.some(e=>e.x<0||e.right>321||e.width<=0))throw Error('main control clipped after larger type '+JSON.stringify(controls));
      const scroll=await page.locator('#b-long-code pre').evaluate(e=>{e.scrollLeft=e.scrollWidth;return {client:e.clientWidth,content:e.scrollWidth,reached:e.scrollLeft};});
      if(!(scroll.content>scroll.client&&scroll.reached>0))throw Error('long code cannot scroll '+JSON.stringify(scroll));
      const overflow=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
      if(overflow.scroll>321)throw Error(template+' '+format+' viewport overflow '+JSON.stringify(overflow));
      await page.screenshot({path:path.join(output,template+'-'+format+'-320.png'),fullPage:true});
      await page.setViewportSize({width:1440,height:1000});
      await page.screenshot({path:path.join(output,template+'-'+format+'-desktop.png'),fullPage:true});
      if(requests.length||errors.length)throw Error(JSON.stringify({requests,errors}));
      rows.push({template,format,status:'passed',blocks:29,viewport:overflow,long_code:scroll,keyboard:'toolbar and nested ToC reached with Tab/Enter',focus,larger_font_controls:controls,external_requests:requests,errors});
      await ctx.close();
    }
    for(const mode of ['no-script','storage-denied']){
      const ctx=await browser.newContext({viewport:{width:320,height:844},javaScriptEnabled:mode!=='no-script'});
      if(mode==='storage-denied')await ctx.addInitScript(()=>{Storage.prototype.getItem=function(){throw new DOMException('Denied','SecurityError')};Storage.prototype.setItem=function(){throw new DOMException('Denied','SecurityError')};});
      const page=await ctx.newPage();await page.goto(pathToFileURL(path.join(directory,'reader-v2-extracted/index.html')).href);
      await expect(page.locator('[data-block-id]')).toHaveCount(29);
      await expect(page.locator('#b-intro [data-language="source"]')).toBeVisible();
      await expect(page.locator('#b-intro [data-language="target"]')).toBeVisible();
      await expect(page.locator('#b-merged-columns')).toHaveAttribute('colspan','2');
      if(mode==='storage-denied')await expect(page.locator('#reader-storage-notice')).toBeVisible();
      rows.push({template:'reader-v2',format:'extracted-zip',mode,status:'passed'});await ctx.close();
    }
  }finally{await browser.close();}
  fs.writeFileSync(path.join(output,'browser-results.json'),JSON.stringify({scope:'M0 authored fixture only',status:'passed',rows},null,2));
  console.log(JSON.stringify(rows));
}
main().catch(e=>{fs.writeFileSync(path.join(output,'browser-failure.txt'),String(e.stack||e));console.error(e);process.exitCode=1;});
