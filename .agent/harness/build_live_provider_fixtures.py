"""Build tiny reviewable original PDFs; does not contact any model or Provider."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import hashlib
import json
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


DESTINATION=ROOT/'fixtures/live-provider'
CASES=[
    {'id':'controlled-en','source_language':'en','target_language':'zh-Hans','font':'Helvetica',
     'source_text':[
         'Controlled translation check',
         'The batch contains 64 tokens.',
         'Do not send a second request if the first result is unknown.',
         'This small test does not establish safety for every document.']},
    {'id':'controlled-zh','source_language':'zh-Hans','target_language':'en','font':'NotoSansSC',
     'source_text':[
         '受控翻译检查',
         '该批次包含64个 token。',
         '如果第一次结果未知，不要发送第二次请求。',
         '这项小测试不能证明所有文档都安全。']},
]


def main():
    DESTINATION.mkdir(parents=True,exist_ok=True)
    font_path=Path('C:/Windows/Fonts/NotoSansSC-VF.ttf')
    pdfmetrics.registerFont(TTFont('NotoSansSC',str(font_path)))
    rows=[]
    for case in CASES:
        path=DESTINATION/(case['id']+'.pdf')
        pdf=canvas.Canvas(str(path),pagesize=(612,792),invariant=1,pageCompression=1)
        pdf.setTitle(case['source_text'][0]);pdf.setAuthor('Local acceptance fixture')
        for index,line in enumerate(case['source_text']):
            pdf.setFont(case['font'],18 if index==0 else 12)
            pdf.drawString(54,730-index*55,line)
        pdf.showPage();pdf.save()
        rows.append({**case,'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                     'byte_size':path.stat().st_size,'page_count':1,
                     'checks':['preserve number 64','preserve negative instruction','preserve conditional unknown outcome','preserve limitation on general safety'],
                     'external_dispatch_authorized':False,'parse_evidence':None,'blocks_to_send':None})
    manifest={'format':'controlled-live-provider-fixtures-v1','purpose':'Reviewable minimal EN-to-ZH and ZH-to-EN tests, only after explicit operator authorization.',
              'not_a_substitute_for':['Efficiently Scaling Transformer Inference source gold','Pathways source gold'],
              'contains_private_content':False,'documents':rows}
    (DESTINATION/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'created':[row['path'] for row in rows],'external_calls':0}))


if __name__=='__main__':main()
