"""Bundle the no-dependency, file://-compatible interaction prototype."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]/'prototype'
css=(ROOT/'src/app.css').read_text('utf-8')
reader_css=(ROOT/'src/reader-v1.css').read_text('utf-8')
parts=[(ROOT/'src'/name).read_text('utf-8') for name in ['icons.js','model.js','reader.js','app.js']]
js='(()=>{\n"use strict";\nconst READER_CSS='+json.dumps(reader_css,ensure_ascii=False)+';\n'+'\n'.join(parts)+'\n})();'
# Protect the enclosing HTML parser, without changing the JS string values.
js=js.replace('</script','<\\/script')
page='''<!doctype html><html lang="zh-CN" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>对照文库 · 个人 PDF 知识库原型 v3</title><meta name="description" content="保留原有双语静态阅读风格的文档库交互原型。仅 PDF 入口；无登录。解析与翻译为明确的固定样例演示。"><style>'''+css+'''</style></head><body><div id="app"></div><div id="toast" class="toast" role="status" aria-live="polite" hidden></div><dialog id="dialog" aria-label="操作确认与详情"></dialog><noscript><div style="padding:3rem;font-family:system-ui"><h1>交互文档库需要 JavaScript</h1><p>静态阅读页的正文不需要 JavaScript。<a href="reader/efficiently-scaling-transformer-inference-bilingual.html">阅读 Transformer 推理论文</a> · <a href="reader/pathways-asynchronous-distributed-dataflow-bilingual.html">阅读 Pathways 论文</a></p></div></noscript><script>'''+js+'''</script></body></html>'''
(ROOT/'index.html').write_text(page,encoding='utf-8')
print('Built',ROOT/'index.html',len(page.encode()),'bytes')
