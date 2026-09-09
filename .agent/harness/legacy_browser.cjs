const {createRequire}=require('node:module');
const path=require('node:path');
const fs=require('node:fs');
const {pathToFileURL}=require('node:url');
const {repoRoot:root,inputPath,outputDirectory}=require('./browser_paths.cjs');
const {chromium,expect}=createRequire(path.join(root,'apps/web/package.json'))('@playwright/test');

async function run(){
 const browser=await chromium.launch({headless:true});
 const directory=inputPath(process.env.LEGACY_BROWSER_INPUT||'evidence/legacy-review');
const output=outputDirectory('legacy_browser');
fs.mkdirSync(output,{recursive:true});
 const manifest=JSON.parse(fs.readFileSync(path.join(root,'reference/legacy-manifest.json')));
 const results=[];
 try{
  for(const document of manifest.documents){
   for(const viewport of [{width:1440,height:1060},{width:390,height:844}]){
    const observations=[];
    for(const variant of ['reference','production','export']){
     const context=await browser.newContext({viewport});
     const page=await context.newPage();
     const errors=[],external=[];
     page.on('pageerror',e=>errors.push(String(e)));
     page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith('http://127.0.0.1:8080/'))external.push(r.url());});
     const url=variant==='reference'?pathToFileURL(path.join(root,document.html_path)).href:
       variant==='production'?'http://127.0.0.1:8080/read/'+document.id+'/zh-Hans':
       pathToFileURL(path.join(directory,document.id+'.html')).href;
     await page.goto(url);
     await page.evaluate(()=>document.fonts.ready);
     await page.locator('img').evaluateAll(nodes=>Promise.all(nodes.map(image=>{image.loading='eager';return image.decode();})));
     await expect(page.locator('.pair').first()).toBeVisible();
     const pairs=await page.locator('.pair').allTextContents();
     const images=await page.locator('img').evaluateAll(nodes=>nodes.map(n=>({src:n.getAttribute('src'),width:n.naturalWidth,height:n.naturalHeight})));
     if(images.some(image=>image.width===0))throw Error(JSON.stringify(images));
     await page.screenshot({path:path.join(output,document.id+'-'+viewport.width+'-'+variant+'.png')});
     await page.locator('[data-language-mode="zh"]').click();
     await expect(page.locator('.pair .para.en').first()).toBeHidden();
     await expect(page.locator('.pair .para.zh').first()).toBeVisible();
     await page.locator('[data-language-mode="both"]').click();
     const firstAnchor=page.locator('.toc a').first();
     if(await firstAnchor.count()){
       const href=await firstAnchor.getAttribute('href');
       await firstAnchor.click();
       if(!page.url().endsWith(href))throw Error('TOC anchor did not navigate');
     }
     if(errors.length||external.length)throw Error(JSON.stringify({errors,external}));
     observations.push({variant,url,title:await page.title(),pair_count:pairs.length,pairs,images:images.length,errors,external});
     await context.close();
    }
    if(JSON.stringify(observations[0].pairs)!==JSON.stringify(observations[1].pairs)||JSON.stringify(observations[0].pairs)!==JSON.stringify(observations[2].pairs))throw Error('Legacy pairing/order changed');
    results.push({document:document.id,viewport,variants:observations.map(({pairs,...rest})=>rest),pair_order_identical:true});
   }
  }
 }finally{await browser.close();}
 fs.writeFileSync(path.join(output,'browser-results.json'),JSON.stringify({status:'passed',browser:'isolated bundled Playwright Chromium',results},null,2));
 console.log(JSON.stringify({status:'passed',documents:2,viewports:2,variants:3,pair_order_identical:true}));
}
run().catch(error=>{console.error(error);process.exitCode=1;});
