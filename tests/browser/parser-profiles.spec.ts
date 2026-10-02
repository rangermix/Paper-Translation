import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';
const active=['surya-ocr-2-v1','chandra-ocr-2-v1','infinity-parser2-pro-v1','infinity-parser2-flash-v1'];
async function setup(page:Page,options:{stale?:boolean;selection?:string;online?:boolean}={}){
  let preferences={generation:3,locale:'zh-Hans',publish_policy:'manual_approval',theme:'light',parser_profile_revision:options.selection??active[0],parser_timeout_seconds:7200};
  const writes:any[]=[],errors:string[]=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/v1/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    if(!['GET','HEAD'].includes(req.method()))writes.push({path,body:req.postDataJSON(),headers:req.headers()});
    if(path.endsWith('/settings/preferences')){
      if(req.method()==='PATCH'){
        if(options.stale)return route.fulfill({status:412,json:{error:{code:'PRECONDITION_FAILED',message:'Stale version'}}});
        preferences={...preferences,...req.postDataJSON(),generation:preferences.generation+1};
      }
      return route.fulfill({json:preferences,headers:{ETag:`"${preferences.generation}"`}});
    }
    if(path.endsWith('/settings/parser-environment'))return route.fulfill({json:{online:options.online??true,system:'Linux',architecture:'x86_64',cpu_count:4,memory_bytes:8*1024**3,default:'dmr',backend:'vllm',options:[{id:'dmr',profiles:active}]}});
    if(path.endsWith('/settings/parser-models'))return route.fulfill({json:{models:[{id:active[0],download_bytes:1374048660,status:'not_downloaded'},{id:active[2],download_bytes:70234587962,status:'not_downloaded'}]}});
    if(path.endsWith('/settings/parser-models/prepare'))return route.fulfill({status:202,json:{status:'downloading'}});
    if(path.endsWith('/settings/provider'))return route.fulfill({json:{configured:false,dispatch_disabled:true,generation:2}});
    if(path.endsWith('/settings/dispatch'))return route.fulfill({json:{generation:3,dispatch_disabled:true,unknown_attempts:0,inflight_requests:0}});
    if(path.endsWith('/capabilities'))return route.fulfill({json:{features:{translation:true},source_mime_types:['application/pdf']}});
    if(path.endsWith('/documents/doc_test'))return route.fulfill({json:{id:'doc_test',title:'Parser choice fixture',source_asset_id:'asset_test',tags:[],editions:[],generation:7,lifecycle:'active',status:'source_only'}});
    if(path.endsWith('/documents/doc_test/parse'))return route.fulfill({status:202,json:{job_id:'parse_test'}});
    if(path.endsWith('/jobs/parse_test'))return route.fulfill({json:{id:'parse_test',stage:'parse',status:'pending',control_epoch:1}});
    return route.fulfill({json:{items:[]}});
  });return {writes,errors};
}
for(const profile of active){
  test(`${profile}: DMR selection persists and per-document choice stays explicit`,async({page})=>{
    const {writes,errors}=await setup(page);await page.goto('/#/settings');
    const panel=page.getByRole('region',{name:'PDF 解析',exact:true});
    await expect(panel.getByLabel('默认 PDF 解析方案').locator('option')).toHaveCount(4);
    await expect(panel).toContainText('运行设备：Docker Model Runner · Compose');
    await panel.getByLabel('默认 PDF 解析方案').selectOption(profile);
    await panel.getByLabel('解析超时（分钟）').fill('180');expect(writes).toHaveLength(0);
    await panel.getByRole('button',{name:'保存解析设置'}).click();await expect(panel).toContainText('解析设置已保存');
    expect(writes[0]).toMatchObject({body:{parser_profile_revision:profile,parser_timeout_seconds:10800},headers:{'if-match':'"3"'}});
    await page.reload();await expect(panel.getByLabel('默认 PDF 解析方案')).toHaveValue(profile);
    await page.goto('/#/documents/doc_test');await expect(page.getByLabel('本次 PDF 解析方案')).toHaveValue(profile);
    await page.getByLabel('本次 PDF 解析方案').selectOption(active[1]);
    await page.getByRole('button',{name:'解析并生成阅读版',exact:true}).click();await expect(page).toHaveURL(/#\/jobs\/parse_test/);
    expect(writes[1]).toMatchObject({body:{source_asset_id:'asset_test',parser_profile_revision:active[1]}});expect(errors).toEqual([]);
  });
}
for(const profile of ['docling-v1','granite-docling-v1','paddleocr-vl-1.6-v1','teleocr-v1','xiaomi-ocr-0-v1']){
  test(`${profile}: saved retired choice is visible and never silently switched`,async({page})=>{
    const {writes}=await setup(page,{selection:profile});await page.goto('/#/settings');const panel=page.getByRole('region',{name:'PDF 解析',exact:true});
    await expect(panel.getByLabel('默认 PDF 解析方案')).toHaveValue(profile);await expect(panel).toContainText('已停用');
    await expect(panel.getByRole('button',{name:'保存解析设置'})).toBeDisabled();await expect(panel.getByRole('button',{name:'准备解析模型',exact:true})).toBeDisabled();
    expect(writes).toHaveLength(0);await panel.getByLabel('默认 PDF 解析方案').selectOption(active[0]);
    await expect(panel.getByRole('button',{name:'保存解析设置'})).toBeEnabled();
  });
}
test('settings reads and saves never download; preparation is explicit',async({page})=>{
  const {writes}=await setup(page);await page.goto('/#/settings');const panel=page.getByRole('region',{name:'PDF 解析',exact:true});
  await expect(panel).toContainText('首次使用时下载');await expect(panel).toContainText('1.37 GB');expect(writes).toHaveLength(0);
  await panel.getByRole('button',{name:'保存解析设置'}).click();await expect(panel).toContainText('解析设置已保存');
  expect(writes.map(w=>w.path)).toEqual(['/api/v1/settings/preferences']);
  await panel.getByRole('button',{name:'准备解析模型',exact:true}).click();await expect(panel).toContainText('已开始准备解析模型');
  expect(writes[1]).toMatchObject({path:'/api/v1/settings/parser-models/prepare',body:{parser_profile_revision:active[0]}});
});
test('stale save preserves the explicit choice and requires refresh',async({page})=>{
  const {writes}=await setup(page,{stale:true});await page.goto('/#/settings');const panel=page.getByRole('region',{name:'PDF 解析',exact:true});
  await panel.getByLabel('默认 PDF 解析方案').selectOption(active[1]);await panel.getByRole('button',{name:'保存解析设置'}).click();
  await expect(panel.getByRole('alert')).toBeVisible();await expect(panel.getByLabel('默认 PDF 解析方案')).toHaveValue(active[1]);
  await expect(panel.getByRole('button',{name:'保存解析设置'})).toBeDisabled();expect(writes).toHaveLength(1);
});
test('mobile controls and default Surya need no writes',async({page})=>{
  await page.setViewportSize({width:390,height:844});const {writes,errors}=await setup(page);
  await page.route('**/api/v1/settings/preferences',route=>route.fulfill({json:{generation:3,parser_timeout_seconds:7200,theme:'light'},headers:{ETag:'"3"'}}));
  await page.goto('/#/settings');await expect(page.getByLabel('默认 PDF 解析方案')).toHaveValue(active[0]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:outputDirectory('parser-dmr-mobile.png'),fullPage:true});expect(writes).toHaveLength(0);expect(errors).toEqual([]);
});
