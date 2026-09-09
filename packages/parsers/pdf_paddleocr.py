"""Official PaddleOCR-VL pipeline, CPU only, with independent PDF evidence."""
from __future__ import annotations

import os
from importlib.metadata import version
from pathlib import Path

from packages.ir import canonical_bytes, digest
from .config import CPU_THREADS
from .inspect import PDFError, inspect_pdf
from .models import verify_models
from .pdf_docling import DoclingParser, overlap
from .profiles import PADDLE_MODEL, PADDLE_PROFILE, selected_profile
from .table_html import TABLE_HTML_VERSION, parse_table_html


def paddle_options(artifacts_path, lock):
    """Only local official models. Keep preprocessing geometry identical to PDF."""
    from paddlex.inference import load_pipeline_config
    config = load_pipeline_config('PaddleOCR-VL-1.6')
    config['batch_size'] = 1
    config['SubModules']['LayoutDetection']['batch_size'] = 1
    config['SubModules']['VLRecognition']['batch_size'] = 1
    repos = {repo['repo_id']: repo for repo in lock['repositories']}
    return dict(pipeline_version='v1.6', device='cpu', engine='paddle', cpu_threads=CPU_THREADS,
        enable_hpi=False, enable_mkldnn=False, enable_cinn=False,
        layout_detection_model_name='PP-DocLayoutV3',
        layout_detection_model_dir=str(artifacts_path / repos['PaddlePaddle/PP-DocLayoutV3']['local_directory']),
        vl_rec_model_name='PaddleOCR-VL-1.6-0.9B',
        vl_rec_model_dir=str(artifacts_path / repos[PADDLE_MODEL]['local_directory']),
        vl_rec_backend='native', use_queues=False,
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_layout_detection=True, use_chart_recognition=False, use_seal_recognition=False,
        format_block_content=False, paddlex_config=config)


def page_items(result, page, image_size):
    """Map official pixel boxes to PDF points; never execute generated HTML."""
    labels = {'doc_title': 'title', 'paragraph_title': 'section_header', 'algorithm': 'code',
        'display_formula': 'formula', 'inline_formula': 'formula', 'image': 'picture',
        'chart': 'picture', 'seal': 'picture', 'header_image': 'picture', 'footer_image': 'picture',
        'figure_title': 'caption', 'header': 'page_header', 'footer': 'page_footer',
        'footnote': 'footnote', 'reference_content': 'reference', 'table': 'table'}
    width, height = image_size
    sx, sy = page['page_size'][0] / width, page['page_size'][1] / height
    items = []
    for i, block in enumerate(result['parsing_res_list']):
        bounds = block['block_bbox']
        if len(bounds) != 4 or not all(isinstance(x, (int, float)) for x in bounds):
            raise PDFError('SOURCE_PARSE_REVIEW', 'Invalid layout coordinates')
        box = [bounds[0] * sx, bounds[1] * sy, bounds[2] * sx, bounds[3] * sy]
        label = labels.get(block['block_label'], 'text')
        text = block['block_content'] or ''
        data = None
        if label == 'table':
            data = parse_table_html(text)
            # Only decoded cell text/row spans enter the IR. Native text is
            # retained for the image fallback; original HTML stays in the JSON.
            text = '\n'.join(r['text'] for r in page['text_regions'] if overlap(r['bbox'], box) >= .9)
        item = {'self_ref': f'paddle-{page["page"]}-{i}', 'label': label,
            'orig': text, 'text': text, 'prov': [{'page_no': page['page'],
                'bbox': dict(zip(('l', 't', 'r', 'b'), box), coord_origin='TOPLEFT')} ]}
        if data is not None: item['data'] = data
        items.append(item)
    return items


class PaddleOCRParser:
    def __init__(self, artifacts_path=None):
        self.artifacts_path = Path(artifacts_path or os.environ.get('DOCLING_ARTIFACTS_PATH', '/opt/docling/models'))

    def parse(self, local_pdf, asset_id, output_dir, profile=None):
        profile = profile or {'parser_profile_revision': PADDLE_PROFILE}
        try:
            selection = selected_profile(profile)
        except ValueError as exc:
            raise PDFError('PARSER_PROFILE_INVALID') from exc
        if set(profile) - {'language', 'limits', 'created_at', 'parser_profile_revision'} or selection != PADDLE_PROFILE:
            raise PDFError('PARSER_PROFILE_INVALID')
        lock = verify_models(self.artifacts_path)
        from .progress import local_identity, report_progress, remaining_seconds
        report_progress('loading_model', model=local_identity(selection, lock))
        for package, key in [('paddleocr', 'paddleocr_version'), ('paddlex', 'paddlex_version'), ('paddlepaddle', 'paddlepaddle_version')]:
            if version(package) != lock[key]:
                raise PDFError('PARSER_VERSION_MISMATCH')
        inspection = inspect_pdf(local_pdf, profile.get('limits'))
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
        os.environ['PADDLE_PDX_DISABLE_DEVICE_FALLBACK'] = 'True'
        os.environ['PADDLE_PDX_LOCAL_FONT_FILE_PATH'] = str(self.artifacts_path / 'RapidOcr/resources/fonts/FZYTK.TTF')
        import numpy as np
        import paddle
        import pypdfium2 as pdfium
        from paddleocr import PaddleOCRVL
        paddle.set_device('cpu')
        pipeline = PaddleOCRVL(**paddle_options(self.artifacts_path, lock))
        report_progress('model_loaded', model=local_identity(selection, lock))
        raw, items = [], []
        try:
            with pdfium.PdfDocument(local_pdf) as pdf:
                for index, page in enumerate(inspection['pages']):
                    report_progress('page_started', page=index + 1, phase='model_inference')
                    pdf_page = pdf[index]
                    try:
                        scale = min(2.0, (40_000_000 / (page['page_size'][0] * page['page_size'][1])) ** .5)
                        bitmap = pdf_page.render(scale=scale)
                        try:
                            image = bitmap.to_pil().convert('RGB')
                            try:
                                import time
                                from datetime import datetime, timezone
                                page_start, page_at = time.monotonic(), datetime.now(timezone.utc).isoformat()
                                recognized_items = None
                                attempts = 0
                                for local_attempt in range(2):
                                    if local_attempt and remaining_seconds() <= 1:
                                        break
                                    if local_attempt:
                                        report_progress('recovery_started', page=index + 1, phase='local_parse')
                                    try:
                                        attempts += 1
                                        results = list(pipeline.predict(np.asarray(image)[:, :, ::-1].copy(), max_new_tokens=4096))
                                        if len(results) == 1:
                                            result = results[0].json['res']
                                            result['page_index'] = index
                                            recognized_items = page_items(result, page, image.size)
                                            raw.append(result)
                                            break
                                    except Exception:
                                        pass  # Preserve this page as native text/original image below.
                                if recognized_items is not None:
                                    items.extend(recognized_items)
                                else:
                                    page['parse_failed'] = True
                                    raw.append({'page_index': index, 'error': {'code': 'PAGE_PARSE_FAILED'}})
                                if local_attempt or recognized_items is None:
                                    inspection.setdefault('automatic_recovery', []).append({
                                        'origin': 'automatic_recovery', 'rule_version': 'paddle-page-retry-v1', 'page': index + 1,
                                        'action': 'local_page_reparse', 'before': [], 'after': [], 'attempts': max(0, attempts - 1),
                                        'started_at': page_at, 'finished_at': datetime.now(timezone.utc).isoformat(),
                                        'elapsed_ms': int((time.monotonic() - page_start) * 1000),
                                        'model': local_identity(selection, lock), 'result': 'recovered' if recognized_items is not None else 'failed'})
                                    report_progress('recovery_completed', page=index + 1, phase='local_parse')
                            finally:
                                image.close()
                        finally:
                            bitmap.close()
                    finally:
                        pdf_page.close()
                    page['ocr_attempted'] = True
                    report_progress('page_completed', page=index + 1, phase='model_inference')
        finally:
            pipeline.close()
        (output / 'paddleocr.json').write_bytes(canonical_bytes({'pages': raw}))
        model = next(repo for repo in lock['repositories'] if repo['repo_id'] == PADDLE_MODEL)
        fingerprint = digest({'profile': PADDLE_PROFILE, 'lock': lock, 'device': 'cpu',
            'threads': CPU_THREADS, 'batch_size': 1, 'scale': 2.0, 'max_new_tokens': 4096,
            'preprocessing': False, 'engine': 'paddle', 'backend': 'native', 'table_adapter': TABLE_HTML_VERSION})
        result = DoclingParser(self.artifacts_path).adapt(items, inspection, local_pdf, asset_id, output,
            profile=profile, parser_version=lock['paddleocr_version'], parser_name='paddleocr',
            enrichment={'model': PADDLE_MODEL, 'revision': model['revision']}, pipeline_hash=fingerprint)
        result['parser_profile_revision'] = PADDLE_PROFILE
        return result
