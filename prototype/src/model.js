const STORE='bilingual-library-personal-pdf-v3';
const LANGS={'zh-Hans':'简体中文','zh-Hant':'繁體中文','en':'English','ja':'日本語','de':'Deutsch'};
const STAGES=['原件接收','PDF 解析','结构预检','逐段翻译','质量校验','静态发布'];
const demoSource=[
 'This is a workflow demonstration, not a translation of the uploaded document.',
 'The experiment uses 64 devices. Each source paragraph is paired with its translation.',
 'A published document remains readable without a translation service.'
];
const demoTargets={
 'zh-Hans':['这是一个流程演示，不是上传文档的译文。','实验使用 64 个设备。每个原文段落都与其译文配对。','发布后的文档无需翻译服务也能继续阅读。'],
 'zh-Hant':['這是一個流程示範，不是上傳文件的譯文。','實驗使用 64 個裝置。每個原文段落都與其譯文配對。','發布後的文件無需翻譯服務也能繼續閱讀。'],
 'en':['This is a workflow demonstration, not a translation of the uploaded document.','The experiment uses 64 devices. Each source paragraph is paired with its translation.','A published document remains readable without a translation service.'],
 'ja':['これは処理のデモであり、アップロードされた文書の翻訳ではありません。','実験では 64 台のデバイスを使用します。原文の各段落は、その翻訳と対になっています。','公開された文書は、翻訳サービスがなくても引き続き読むことができます。'],
 'de':['Dies ist eine Demonstration des Ablaufs, keine Übersetzung des hochgeladenen Dokuments.','Das Experiment verwendet 64 Geräte. Jeder Absatz des Originals wird seiner Übersetzung zugeordnet.','Ein veröffentlichtes Dokument bleibt auch ohne Übersetzungsdienst lesbar.'],
};
function defaultState(){return {version:3,theme:'light',defaults:{language:'zh-Hans',autoPublish:false},documents:[
 {id:'efficient',title:'Efficiently Scaling Transformer Inference',titleZh:'高效扩展 Transformer 推理',language:'zh-Hans',kind:'legacy',source:'PDF',createdAt:'2026-09-02T15:00:00Z',starred:false,filename:'efficiently-scaling-transformer-inference-bilingual.html',pages:18,pairs:99,tags:['Transformer','推理优化'],template:'reader-v1',revision:1,snippet:'We study the problem of efficient generative inference for Transformer models.',snippetZh:'我们研究 Transformer 模型的高效生成式推理问题。'},
 {id:'pathways',title:'Pathways: Asynchronous Distributed Dataflow for ML',titleZh:'PATHWAYS：面向机器学习的异步分布式数据流',language:'zh-Hans',kind:'legacy',source:'PDF',createdAt:'2026-09-02T14:00:00Z',starred:false,filename:'pathways-asynchronous-distributed-dataflow-bilingual.html',pages:20,pairs:87,tags:['分布式系统','TPU'],template:'reader-v1',revision:1,snippet:'Our system, PATHWAYS, is explicitly designed to enable exploration of new systems and machine-learning research ideas.',snippetZh:'PATHWAYS 被明确设计为支持对新型系统与机器学习研究想法的探索。'}
 ],jobs:[],glossary:[{id:'g1',source:'prefill',target:'预填充',language:'zh-Hans'},{id:'g2',source:'tensor parallelism',target:'张量并行',language:'zh-Hans'},{id:'g3',source:'KV cache',target:'KV 缓存',language:'zh-Hans'}],glossaryVersion:1};}
let storageAvailable=true,state;
try{const raw=localStorage.getItem(STORE);state=raw?JSON.parse(raw):defaultState();if(state.version!==3||!Array.isArray(state.documents)||!Array.isArray(state.jobs))state=defaultState();}catch(e){state=defaultState();storageAvailable=false;}
function save(){try{localStorage.setItem(STORE,JSON.stringify(state));}catch(e){storageAvailable=false;toast('浏览器存储不可用；当前操作仅保留到本次页面关闭。请导出需要的内容。');}}
function uuid(){return globalThis.crypto?.randomUUID?.()||'id-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);}
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function getDoc(id){return state.documents.find(d=>d.id===id);}
function getJob(id){return state.jobs.find(j=>j.id===id);}
function fmtDate(t){return new Date(t).toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'});}
function timeNow(){return new Date().toLocaleTimeString('zh-CN',{hour12:false});}
function logJob(j,text){j.log.push({at:timeNow(),text});}
function languageOptions(selected){return Object.entries(LANGS).map(([v,l])=>`<option value="${v}" ${v===selected?'selected':''}>${l}</option>`).join('');}

const originalFiles=new Map();
function isActive(j){return !['published','cancelled','failed'].includes(j.status);}
function jobLabel(j){return ({queued:'待处理',running:'处理中',preflight:'等待预检确认',needs_review:'待校对',ready:'可发布',published:'已发布',paused:'已暂停',cancelled:'已取消'})[j.status]||j.status;}
function newJob(origin,language,issue,sourceDocId=null){
 const j={id:uuid(),origin,language,source:'PDF',sourceDocId,issue,createdAt:new Date().toISOString(),step:0,status:'queued',translation:demoTargets[language][1],glossaryVersion:state.glossaryVersion,confirmed:false,log:[]};
 logJob(j,'创建固定3段的流程演示；没有上传或解析该PDF正文，没有模型调用。');state.jobs.unshift(j);save();return j;
}
function advanceJob(j){
 if(!['queued','running'].includes(j.status))return;
 j.step++;j.status='running';
 if(j.step===2){j.status='preflight';logJob(j,'演示预检就绪：固定3段样本。需要明确确认后才能继续。');}
 else if(j.step===4){logJob(j,'固定样本已进入质量校验。');}
 else if(j.step>=5){if(j.issue){j.status='needs_review';j.translation=demoTargets[j.language][1].replace('64','32');logJob(j,'演示错误：保护数字64被译为32，阻止发布。');}else{j.status='ready';logJob(j,'示例检查通过；尚未代表任何真实PDF的翻译。');}}
 else logJob(j,STAGES[j.step]+'（模拟）。');save();render();
}
function publishJob(j){
 if(j.status!=='ready')return;
 const doc={id:uuid(),title:'流程样例 · '+j.origin,titleZh:'演示内容，不是所选 PDF 的译文',language:j.language,sourceLanguage:'en',source:'PDF',kind:'demo',createdAt:new Date().toISOString(),starred:false,template:'reader-v1',revision:1,generation:1,pairs:3,tags:['流程样例'],note:'这是固定三段内容的交互演示，不是上传PDF的提取或翻译；没有调用模型。当前修改只保存在浏览器。',blocks:demoSource.map((t,i)=>({id:'demo-b'+i,type:'paragraph',source:t,target:i===1?j.translation:demoTargets[j.language][i],reviewed:false,version:1})),history:[]};
 doc.history.push({revision:1,blocks:structuredClone(doc.blocks),reason:'演示发布',time:new Date().toISOString()});state.documents.unshift(doc);j.status='published';j.step=6;j.docId=doc.id;logJob(j,'生成带明确演示说明的静态样例，不修改原PDF条目。');save();navigate('reader/'+doc.id);
}
