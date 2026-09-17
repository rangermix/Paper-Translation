// Independent browser review. Browser plugin not available; isolated bundled Playwright Chromium.
const {createRequire}=require('node:module');
const path=require('node:path');
const fs=require('node:fs');
const {pathToFileURL}=require('node:url');
const {repoRoot:root,inputPath,outputDirectory}=require('./browser_paths.cjs');
const appRequire=createRequire(path.join(root,'src/apps/web/package.json'));
const {chromium,expect}=appRequire('@playwright/test');

async function run(){
  const browser=await chromium.launch({headless:true});
  const directory=inputPath(process.env.READER_BROWSER_INPUT||'evidence/reader-review');
const output=outputDirectory('reader_browser');
fs.mkdirSync(output,{recursive:true});
  const results=[];
  try{
    for(const template of ['reader-v1','reader-v2']){
      const context=await browser.newContext({viewport:{width:1440,height:1000}});
      const page=await context.newPage();
      const errors=[],network=[];
      page.on('pageerror',error=>errors.push(String(error)));
      page.on('request',request=>{if(/^https?:/.test(request.url()))network.push(request.url());});
      await page.goto(pathToFileURL(path.join(directory,template+'.html')).href);
      await expect(page).toHaveTitle('出版契约样例');
      await expect(page.locator('[data-block-id]')).toHaveCount(14);
      await expect(page.getByText('The job has', {exact:false})).toBeVisible();
      await expect(page.getByText('该任务有',{exact:false})).toBeVisible();
      await expect(page.locator('a[download]')).toHaveCount(0);
      await expect(page.locator('figure img')).toHaveJSProperty('naturalWidth',360);
      await page.screenshot({path:path.join(output,template+'-desktop.png'),fullPage:true});
      await page.getByRole('button',{name:'译文',exact:true}).click();
      await expect(page.locator('#b-p1 [data-language="source"]')).toBeHidden();
      await expect(page.locator('#b-p1 [data-language="target"]')).toBeVisible();
      await page.getByRole('button',{name:'双语',exact:true}).click();
      await page.getByRole('button',{name:'切换主题',exact:true}).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
      await page.getByRole('button',{name:'增大字号',exact:true}).click();
      await page.locator('#b-p2 a').first().click();
      await expect(page).toHaveURL(/#b-fn1$/);
      await page.getByRole('link',{name:'返回引用位置'}).click();
      await expect(page).toHaveURL(/#b-p2$/);
      await page.setViewportSize({width:390,height:844});
      await page.screenshot({path:path.join(output,template+'-mobile.png'),fullPage:true});
      const overflow=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));
      if(overflow.scroll>overflow.width+1)throw Error(template+' horizontal overflow '+JSON.stringify(overflow));
      if(errors.length||network.length)throw Error(JSON.stringify({errors,network}));
      results.push({template,mode:'interactive file export',status:'passed',blocks:14,errors,network,overflow});
      await context.close();

      for(const mode of ['no-script','storage-denied']){
        const disabled=await browser.newContext({javaScriptEnabled:mode!=='no-script',viewport:{width:390,height:844}});
        if(mode==='storage-denied')await disabled.addInitScript(()=>{
          Storage.prototype.getItem=function(){throw new DOMException('Denied','SecurityError')};
          Storage.prototype.setItem=function(){throw new DOMException('Denied','SecurityError')};
        });
        const doc=await disabled.newPage();
        await doc.goto(pathToFileURL(path.join(directory,template+'.html')).href);
        await expect(doc.locator('#b-p1 [data-language="source"]')).toBeVisible();
        await expect(doc.locator('#b-p1 [data-language="target"]')).toBeVisible();
        await expect(doc.locator('[data-block-id]')).toHaveCount(14);
        if(mode==='storage-denied')await expect(doc.locator('#reader-storage-notice')).toBeVisible();
        await doc.screenshot({path:path.join(output,template+'-'+mode+'.png'),fullPage:true});
        results.push({template,mode,status:'passed',blocks:14});
        await disabled.close();
      }
    }
  }finally{await browser.close();}
  fs.writeFileSync(path.join(output,'browser-results.json'),JSON.stringify({status:'passed',browser:'isolated bundled Playwright Chromium',results},null,2));
  console.log(JSON.stringify(results));
}
run().catch(error=>{console.error(error);process.exitCode=1;});
