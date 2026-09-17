import json
import tempfile
import unittest
from pathlib import Path

from packages.parsers import PDFError, inspect_pdf
from packages.parsers.pdf_docling import DoclingParser, coverage_report
from packages.parsers.spool import validate_request, verify_result

ROOT = Path(__file__).resolve().parents[2]


class PDFParsing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_inspector_reads_real_pdf(self):
        result = inspect_pdf(ROOT/'tests/fixtures/sample.pdf')
        self.assertEqual(result['page_count'],1)
        self.assertEqual(result['media_type'],'application/pdf')
        self.assertGreater(result['pages'][0]['text_characters'],0)

    def test_disguised_pdf(self):
        fake = self.path/'x.pdf'; fake.write_bytes(b'<html>fake</html>')
        with self.assertRaises(PDFError) as ctx: inspect_pdf(fake)
        self.assertEqual(ctx.exception.code,'UNSUPPORTED_FORMAT')

    def test_encrypted_pdf(self):
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(width=612,height=792); writer.encrypt('secret')
        file = self.path/'encrypted.pdf'
        with file.open('wb') as handle: writer.write(handle)
        with self.assertRaises(PDFError) as ctx: inspect_pdf(file)
        self.assertEqual(ctx.exception.code,'PDF_ENCRYPTED')

    def test_actual_byte_limit(self):
        with self.assertRaises(PDFError) as ctx: inspect_pdf(ROOT/'tests/fixtures/sample.pdf',{'max_bytes':10})
        self.assertEqual(ctx.exception.code,'UPLOAD_TOO_LARGE')

    def test_page_limit(self):
        with self.assertRaises(PDFError) as ctx: inspect_pdf(ROOT/'tests/fixtures/sample.pdf',{'max_pages':0})
        self.assertEqual(ctx.exception.code,'PDF_PAGE_LIMIT')

    def test_rotated_cropbox_coordinates_retain_title(self):
        from pypdf import PdfReader,PdfWriter
        page=PdfReader(ROOT/'tests/fixtures/sample.pdf').pages[0]
        page.rotate(90);page.cropbox.lower_left=(20,30);page.cropbox.upper_right=(590,770)
        writer=PdfWriter();writer.add_page(page);file=self.path/'rotated.pdf'
        with file.open('wb') as handle:writer.write(handle)
        result=inspect_pdf(file)['pages'][0]
        self.assertEqual(result['page_size'],[740,570])
        title=next(r for r in result['text_regions'] if 'Publication' in r['text'])
        self.assertGreater(title['bbox'][0],600)
        self.assertLess(title['bbox'][1],100)

    def test_models_missing_never_fallback_or_download(self):
        with self.assertRaises(PDFError) as ctx:
            DoclingParser(artifacts_path=self.path/'absent').parse(ROOT/'tests/fixtures/sample.pdf','asset_test',self.path/'result')
        self.assertEqual(ctx.exception.code,'PARSER_MODELS_MISSING')

    def test_spool_rejects_paths_secrets_and_stale_fence(self):
        with self.assertRaises(ValueError): validate_request({'path':'../../etc/passwd','api_key':'secret'})
        with self.assertRaises(ValueError):
            verify_result(self.path,{'task_id':'t','fence':1,'source_sha256':'a'*64}, {'task_id':'t','fence':2,'source_sha256':'a'*64,'files':[]})

    def test_coverage_missing_page_is_blocking(self):
        pages = [{'page':1,'page_size':[600,800],'text_characters':30,'scan_suspected':False,'text_regions':[{'bbox':[20,20,100,40],'text':'Important original sentence.'}]}]
        report = coverage_report(pages,[],[])
        self.assertFalse(report['can_translate'])
        self.assertEqual(report['unresolved'][0]['code'],'SOURCE_PARSE_REVIEW')

    def test_coverage_scan_never_marked_success_by_image(self):
        pages = [{'page':1,'page_size':[600,800],'text_characters':0,'scan_suspected':True,'text_regions':[]}]
        report = coverage_report(pages,[],[{'page':1,'reason':'picture'}])
        self.assertFalse(report['can_translate'])
        self.assertEqual(report['unresolved'][0]['code'],'OCR_REQUIRED')


if __name__ == '__main__': unittest.main()
