"""Regressions discovered by independent, real offline Docling executions."""
from pathlib import Path
import unittest

from packages.parsers import inspect_pdf
from packages.parsers.pdf_docling import coverage_report, table_grid_complete, _source_nodes

ROOT = Path(__file__).resolve().parents[2]


class NativeCoverageRegressions(unittest.TestCase):
    def test_cjk_adjacent_numbers_are_protected_without_splitting_identifiers(self):
        atoms={}
        nodes=_source_nodes('包含64个、3.5倍和100%，标识abc64x及v2保持。','b',atoms,'paragraph')
        self.assertEqual([atom['value'] for atom in atoms.values()],['64','3.5','100%'])
        reconstructed=''.join(node['text'] if node['type']=='text' else atoms[node['ref']]['value'] for node in nodes)
        self.assertEqual(reconstructed,'包含64个、3.5倍和100%，标识abc64x及v2保持。')

    def test_real_pdf_records_embedded_image_and_vector_table_regions(self):
        page = inspect_pdf(ROOT / 'fixtures/sample.pdf')['pages'][0]
        self.assertEqual(len(page['image_regions']), 1)
        self.assertTrue(page['graphic_regions'])

    def test_nonempty_text_does_not_excuse_missing_native_graphics(self):
        page = {'page':1,'page_size':[600,800],'scan_suspected':False,'text_characters':4,
                'text_regions':[{'bbox':[10,10,50,20],'text':'Text'}],
                'image_regions':[{'bbox':[50,100,250,250]}]}
        block = {'id':'text','kind':'paragraph','raw_text':'Text','warnings':[], 'attributes':{},
                 'provenance':[{'page':1,'bbox':[10,10,50,20],'page_size':[600,800]}]}
        report=coverage_report([page],[block],[])
        self.assertFalse(report['can_translate'])
        self.assertIn('Native graphic', report['unresolved'][0]['reason'])

    def test_small_declared_original_figure_can_retain_internal_label(self):
        box=[50,100,250,250]
        page={'page':1,'page_size':[600,800],'scan_suspected':False,'text_characters':4,
              'text_regions':[{'bbox':[60,110,80,120],'text':'Axis'}], 'image_regions':[{'bbox':box}]}
        block={'id':'figure','kind':'figure','raw_text':'','warnings':['Original image, internal text retained'],
               'attributes':{},'provenance':[{'page':1,'bbox':box,'page_size':[600,800]}]}
        self.assertTrue(coverage_report([page],[block],[])['can_translate'])
        block['provenance'][0]['bbox']=[0,0,600,800]
        self.assertFalse(coverage_report([page],[block],[])['can_translate'])

    def test_invalid_table_grid_does_not_become_structured(self):
        cell={'text':'A','start_row_offset_idx':0,'end_row_offset_idx':1,'start_col_offset_idx':0,'end_col_offset_idx':1}
        self.assertTrue(table_grid_complete({'num_rows':1,'num_cols':1,'table_cells':[cell]}))
        self.assertFalse(table_grid_complete({'num_rows':1,'num_cols':2,'table_cells':[cell]}))
        self.assertFalse(table_grid_complete({'num_rows':1,'num_cols':1,'table_cells':[cell,cell]}))


if __name__ == '__main__':
    unittest.main()
