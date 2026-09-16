import { test, expect } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { inputPath, outputDirectory } from './paths';

test.beforeEach(() => {
  test.skip(process.env.LIBRARY_LIVE_BROWSER !== '1', 'Set LIBRARY_LIVE_BROWSER=1 only for the designated acceptance instance.');
  expect(process.env.LIBRARY_BROWSER_URL, 'Live browser tests require an explicit LIBRARY_BROWSER_URL').toBeTruthy();
});
import { resolve } from 'node:path';
import { readFile, writeFile } from 'node:fs/promises';

test('real database document title tags and star survive cleared browser storage and a fresh anonymous context',async({page,context,browser})=>{
  const previous=JSON.parse(await readFile(inputPath(process.env.LIBRARY_LIVE_RECEIPT ?? resolve(outputDirectory('live'), 'live-multiple-independent.json')),'utf8'));
  const baseURL=process.env.LIBRARY_BROWSER_URL!;
  const documentId=previous.href.split('/').at(-1);
  await page.goto('/#/library');
  await page.getByLabel('文档范围').selectOption('archived');
  await page.getByLabel('搜索题名').fill(previous.title);
  await page.getByRole('button',{name:'搜索',exact:true}).click();
  const star=page.getByRole('button',{name:`收藏 ${previous.title}`,exact:true});
  if(await star.isVisible()) await star.click();
  await expect(page.getByRole('button',{name:`取消收藏 ${previous.title}`,exact:true})).toBeVisible();
  await page.goto(`/${previous.href}`);
  const before=await page.request.get(`/api/v1/documents/${documentId}`).then(r=>r.json());
  expect(before.starred).toBe(true);expect(before.tags).toEqual(expect.arrayContaining(['agent-acceptance','upload-isolation']));
  await context.addCookies([{name:'independent_storage_sentinel',value:'disposable',url:baseURL}]);
  await page.evaluate(()=>{localStorage.setItem('independent_storage_sentinel','disposable');sessionStorage.setItem('independent_storage_sentinel','disposable');localStorage.clear();sessionStorage.clear();});
  await context.clearCookies();
  await page.reload();
  await expect(page.getByRole('heading',{name:previous.title,exact:true})).toBeVisible();
  await expect(page.getByText('agent-acceptance · upload-isolation',{exact:true})).toBeVisible();
  const after=await page.request.get(`/api/v1/documents/${documentId}`).then(r=>r.json());
  expect(after).toMatchObject({id:before.id,title:before.title,starred:true,tags:before.tags,generation:before.generation});
  expect(await context.cookies()).toEqual([]);
  expect(await page.evaluate(()=>[localStorage.length,sessionStorage.length])).toEqual([0,0]);
  const fresh=await browser.newContext({baseURL,viewport:{width:1280,height:900}});
  try{
    const next=await fresh.newPage();const responses:{url:string;status:number}[]=[];
    next.on('response',r=>{if(r.url().includes('/api/'))responses.push({url:r.url(),status:r.status()});});
    await next.goto(`/${previous.href}`);
    await expect(next.getByRole('heading',{name:previous.title,exact:true})).toBeVisible();
    await expect(next.getByText('agent-acceptance · upload-isolation',{exact:true})).toBeVisible();
    const independent=await next.request.get(`/api/v1/documents/${documentId}`).then(r=>r.json());
    expect(independent).toMatchObject({id:before.id,title:before.title,starred:true,tags:before.tags,generation:before.generation});
    await next.goto('/#/library');await next.getByLabel('文档范围').selectOption('archived');
    await next.getByLabel('搜索题名').fill(previous.title);await next.getByRole('button',{name:'搜索',exact:true}).click();
    await expect(next.getByRole('button',{name:`取消收藏 ${previous.title}`,exact:true})).toBeVisible();
    expect(responses.some(r=>r.status===401||r.status===403||/\/users|\/workspaces|\/login/.test(r.url))).toBe(false);
    await next.screenshot({path:resolve(outputDirectory('live'), 'live-storage-fresh-context.png'),fullPage:true});
    await writeFile(resolve(outputDirectory('live'), 'live-storage-cleared.json'),JSON.stringify({kind:'actual_browser_actual_HTTP_same_database',baseURL,document_id:documentId,title:before.title,tags:before.tags,starred:true,generation:before.generation,cleared_localStorage:true,cleared_sessionStorage:true,cleared_cookies:true,fresh_context:true,authentication_required:false,responses,provider_calls:0,migration_schema_scope:'This browser test does not inspect migration DDL.'},null,2));
  }finally{await fresh.close();}
});
