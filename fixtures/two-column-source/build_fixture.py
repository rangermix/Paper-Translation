"""Author the PDF and a visible-layout oracle, never parser IR.

Run with a Python environment containing ReportLab. The frozen PDF is the test
input; rebuilding it is not part of normal acceptance or runtime execution.
"""
import hashlib
import json
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

ROOT=Path(__file__).resolve().parent
PDF=ROOT/'two-column-source.pdf'
canvas=Canvas(str(PDF),pagesize=(612,792),invariant=1,pageCompression=1)
canvas.setTitle('Two column source ordering fixture')
items=[]

def paragraph(key,text,x,top,page,kind='paragraph',size=10.5,width=234):
    words=text.split();lines=[];line=''
    for word in words:
        candidate=(line+' '+word).strip()
        if line and stringWidth(candidate,'Helvetica',size)>width:
            lines.append(line);line=word
        else:line=candidate
    if line:lines.append(line)
    canvas.setFont('Helvetica',size)
    boxes=[]
    for index,line in enumerate(lines):
        baseline=792-top-index*14
        canvas.drawString(x,baseline,line)
        boxes.append({'page':page,'text':line,'bbox':[x,top+index*14-size,x+stringWidth(line,'Helvetica',size),top+index*14+3]})
    items.append({'key':key,'kind':kind,'page':page,'column':'left' if x<300 else 'right','text':text,
        'lines':boxes,'bbox':[x,top-size,max(b['bbox'][2] for b in boxes),boxes[-1]['bbox'][3]]})

def title(text,top,page,level=1,x=54):
    canvas.setFont('Helvetica-Bold',16 if level==1 else 12)
    canvas.drawString(x,792-top,text)
    items.append({'key':'title' if level==1 else text.lower(),'kind':'heading','page':page,'level':level,
        'text':text,'bbox':[x,top-(16 if level==1 else 12),x+stringWidth(text,'Helvetica-Bold',16 if level==1 else 12),top+3]})

title('Two column source ordering fixture',54,1)
paragraph('alpha','The first column starts with the orchard study. Researchers label each tree before they collect the leaves. The labels connect the field notes with the stored samples. This opening paragraph describes the preparation stage and gives the first step in the reading sequence.',54,104,1)
paragraph('beta','The second paragraph stays in the left column. The team records the shade around each tree and places each sample in a clean container. These observations provide context for the later measurements. The complete left column is read before the right column begins.',54,290,1)
paragraph('gamma','The right column begins with the laboratory stage. Each container receives the same handling procedure. The researchers record the preparation time and retain the original observation sheet. This paragraph follows both paragraphs in the left column and introduces the final stage.',324,104,1)
paragraph('continuation_a','The final paragraph on this page describes the transfer of the records. A reviewer compares the container labels with the observation sheet and checks the reading sequence in the source document. This paragraph continues on the following page and',324,290,1)
canvas.setFont('Helvetica',9);canvas.drawString(303,32,'1');canvas.showPage()

paragraph('continuation_b','keeps the same subject while moving to the first column. The reviewer places the checked record beside the corresponding sample. This completes the paragraph that began in the right column of the previous page.',54,62,2)
paragraph('epsilon','A separate paragraph begins after the continued record. It describes how the team stores the completed sheets in a local folder. The folder preserves the original sequence and provides a stable reference for later review. This paragraph ends before the checklist in the right column.',54,220,2)
title('Checklist',54,2,2,324)
paragraph('list_a','- Compare the sample label with its observation sheet.',324,84,2,'list_item')
paragraph('list_b','- Store the checked record beside the sample.',324,144,2,'list_item')
title('References',270,2,2,324)
paragraph('reference_a','Adams, A. Orchard observation records. Local Methods Series, 2024.',324,300,2,'reference')
paragraph('reference_b','Baker, B. Preserving the reading sequence. Field Review Notes, 2025.',324,360,2,'reference')
canvas.setFont('Helvetica',9);canvas.drawString(303,32,'2');canvas.save()
expected={'scope':'Author-visible original PDF text and positions, not hand-authored parser IR or translated output',
    'pdf_sha256':hashlib.sha256(PDF.read_bytes()).hexdigest(),'page_size':[612,792],
    'reading_sequence':[i['key'] for i in items], 'items':items,
    'continuation':{'parts':['continuation_a','continuation_b'],'text':next(i['text'] for i in items if i['key']=='continuation_a')+' '+next(i['text'] for i in items if i['key']=='continuation_b')}}
(ROOT/'expected-visible.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(expected['pdf_sha256'])
