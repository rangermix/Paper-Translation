"""Author inert, bounded PDF rejection/retention fixtures; never execute PDF actions."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
    NameObject, NumberObject, TextStringObject)
from reportlab.pdfgen.canvas import Canvas


OUTPUT = ROOT / 'fixtures/security'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'fixtures/sample.pdf'
    writer = PdfWriter()
    writer.append(source)
    writer.encrypt('controlled-test-password')
    writer.write(OUTPUT / 'encrypted.pdf')
    writer = PdfWriter()
    for _ in range(201):
        writer.add_blank_page(width=595, height=842)
    writer.write(OUTPUT / '201-pages.pdf')
    writer = PdfWriter()
    writer.add_blank_page(width=22001, height=842)
    writer.write(OUTPUT / 'oversized-page.pdf')
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    stream = DecodedStreamObject()
    stream.set_data(b'\x00')
    stream.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
        NameObject('/Width'): NumberObject(10000), NameObject('/Height'): NumberObject(10000),
        NameObject('/ColorSpace'): NameObject('/DeviceGray'), NameObject('/BitsPerComponent'): NumberObject(8)})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Im1'): writer._add_object(stream)})})
    content = DecodedStreamObject()
    content.set_data(b'q 595 0 0 842 0 0 cm /Im1 Do Q')
    page[NameObject('/Contents')] = writer._add_object(content)
    writer.write(OUTPUT / 'oversized-image.pdf')
    raster = Image.new('RGB', (595, 842), 'white')
    draw = ImageDraw.Draw(raster)
    draw.text((45, 70), 'Controlled scanned body. OCR is required.', fill='black')
    for row in range(8):
        draw.text((45, 130 + row * 42), 'This body is pixels, without a native text layer.', fill='black')
    raster.save(OUTPUT / 'scan-body.png')
    for name, mixed in [('scan-only.pdf', False), ('mixed-scan.pdf', True)]:
        canvas = Canvas(str(OUTPUT / name), pagesize=(595, 842), invariant=1)
        if mixed:
            canvas.drawString(45, 770, 'Controlled native first page')
            canvas.drawString(45, 720, 'The next scanned body must block full-document translation.')
            canvas.showPage()
        canvas.drawImage(str(OUTPUT / 'scan-body.png'), 0, 0, width=595, height=842)
        canvas.showPage()
        canvas.save()
    writer = PdfWriter()
    writer.append(source)
    writer.add_js('app.launchURL("http://127.0.0.1:18765/pdf-action-must-not-run", true);')
    writer.add_attachment('embedded-source-must-not-be-imported.txt', b'INERT_ATTACHMENT_SENTINEL')
    writer.root_object[NameObject('/OpenAction')] = DictionaryObject({NameObject('/S'): NameObject('/URI'),
        NameObject('/URI'): TextStringObject('http://127.0.0.1:18765/pdf-action-must-not-run'),
        NameObject('/Next'): DictionaryObject({NameObject('/S'): NameObject('/Launch'),
            NameObject('/F'): TextStringObject('/tmp/pdf-action-must-not-run')})})
    writer.write(OUTPUT / 'inert-actions-attachment.pdf')
    (OUTPUT / 'malformed.pdf').write_bytes(b'%PDF-1.7\nControlled invalid decoder input\n%%EOF')
    report = {'kind': 'authored_security_fixtures_not_source_gold', 'files': []}
    expected = {'encrypted.pdf': 'PDF_ENCRYPTED', '201-pages.pdf': 'PDF_PAGE_LIMIT',
        'oversized-page.pdf': 'PDF_RESOURCE_LIMIT', 'oversized-image.pdf': 'PDF_RESOURCE_LIMIT',
        'malformed.pdf': 'PDF_INVALID', 'scan-only.pdf': 'retained_original_then_OCR_REQUIRED',
        'mixed-scan.pdf': 'retained_original_then_OCR_REQUIRED', 'inert-actions-attachment.pdf': 'retained_original_without_execution_or_attachment_import'}
    for name, outcome in expected.items():
        data = (OUTPUT / name).read_bytes()
        report['files'].append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'byte_size': len(data), 'expected': outcome})
    (OUTPUT / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
