"""Pinned local vision parsers with native Transformers or Docker Model Runner."""
from __future__ import annotations

import base64
from importlib.metadata import version
import io
import os
from pathlib import Path
import re

import httpx
from packages.ir import canonical_bytes, digest
from .catalog import vlm_lock, vlm_model
from .inspect import PDFError, inspect_pdf
from .pdf_docling import DoclingParser
from .preparation import model_directory
from .profiles import (CHANDRA_PROFILE, INFINITY_FLASH_PROFILE, INFINITY_PRO_PROFILE,
                       SURYA_PROFILE, TELEOCR_PROFILE, VLM_PROFILES, XIAOMI_PROFILE, selected_profile)
from .runtime import require_device, runtime_config
from .vlm_output import bbox, html_items, item, json_items, markdown_items, otsl_table, strip_fences

PROMPTS = {
    SURYA_PROFILE: 'OCR this image to HTML. Each block is a div with data-label and data-bbox (x0 y0 x1 y1, normalized 0-1000).',
    CHANDRA_PROFILE: 'OCR this image to HTML, arranged as layout blocks.  Each layout block should be a div with the data-bbox attribute representing the bounding box of the block in x0 y0 x1 y1 format.  Bboxes are normalized 0-1000. The data-label attribute is the label for the block.\nUse the following labels: Caption, Footnote, Equation-Block, List-Group, Page-Header, Page-Footer, Image, Section-Header, Table, Text, Complex-Block, Code-Block, Form, Table-Of-Contents, Figure, Chemical-Block, Diagram, Bibliography, Blank-Page.\nInline math: Surround math with <math>...</math> tags. Math expressions should be rendered in KaTeX-compatible LaTeX. Use display for block math.\nTables: Use colspan and rowspan attributes to match table structure.\nText: join lines together properly into paragraphs using <p>...</p> tags. Reading order should be correct and natural.',
    INFINITY_FLASH_PROFILE: '- Extract layout information from the provided PDF image.\n- For each layout element, output its bbox, category, and the text content within the bbox.\n- Bbox format: [x1, y1, x2, y2].\n- Allowed layout categories: [\'header\', \'title\', \'text\', \'figure\', \'table\', \'formula\', \'figure_caption\', \'table_caption\', \'formula_caption\', \'figure_footnote\', \'table_footnote\', \'page_footnote\', \'footer\'].\n- Text extraction and formatting:\n  1) For \'figure\', the text field must be an empty string.\n  2) For \'formula\', format text as LaTeX.\n  3) For \'table\', format text as HTML.\n  4) For all other categories (e.g., text, title), format text as Markdown.\n- The output text must be exactly the original text from the image, with no translation or rewriting.\n- Sort all layout elements in human reading order.\n- Final output must be a single JSON object.',
    TELEOCR_PROFILE: 'Analyze the image layout.',
    XIAOMI_PROFILE: 'Extract all information from the main body of the document image and represent it in markdown format, ignoring headers and footers. Tables should be expressed in OTSL format, formulas in the document should be represented using LATEX format, and the parsing should be organized according to the reading order.',
}
PROMPTS[INFINITY_PRO_PROFILE] = PROMPTS[INFINITY_FLASH_PROFILE]


class NativeVision:
    def __init__(self, model, root, runtime):
        from .preparation import verify_cached_models
        verify_cached_models(model['id'], root)
        os.environ['HF_HUB_OFFLINE'] = os.environ['TRANSFORMERS_OFFLINE'] = '1'
        os.environ['HF_MODULES_CACHE'] = '/tmp/parser-hf-modules'
        import torch
        from transformers import AutoModel, AutoModelForImageTextToText, AutoProcessor
        if version('transformers') != model.get('transformers_version', vlm_lock()['transformers_version']):
            raise PDFError('PARSER_VERSION_MISMATCH')
        path = model_directory(model['id'], root)
        # The custom TeleOCR module is local, revision pinned and hash checked.
        trust = model['trust_remote_code']
        self.processor = AutoProcessor.from_pretrained(path, local_files_only=True, trust_remote_code=trust)
        dtype = torch.bfloat16 if runtime.device != 'cpu' or model['parameter_size'] >= 4 else torch.float32
        factory = AutoModel if trust else AutoModelForImageTextToText
        self.model = factory.from_pretrained(path, local_files_only=True, trust_remote_code=trust,
                                            dtype=dtype, attn_implementation='sdpa').to(runtime.device).eval()
        self.runtime, self.teleocr = runtime, trust

    def __call__(self, image, prompt):
        import torch
        from .progress import remaining_seconds
        messages = [{'role': 'user', 'content': [{'type': 'image'}, {'type': 'text', 'text': prompt}]}]
        if self.teleocr:
            messages.insert(0, {'role': 'system', 'content': 'You are a helpful assistant.'})
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                                 **({} if self.teleocr else {'enable_thinking': False}))
        inputs = self.processor(text=[text], images=[image], return_tensors='pt').to(self.runtime.device)
        with torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=8192, do_sample=False,
                                         max_time=max(1, remaining_seconds()))
        return self.processor.batch_decode(output[:, inputs['input_ids'].shape[1]:], skip_special_tokens=True)[0]


class DockerVision:
    def __init__(self, model, root, runtime):
        self.model, self.runtime = model, runtime

    def __call__(self, image, prompt):
        from .progress import remaining_seconds
        from .model_service import dmr_flags
        runtime = self.runtime
        root = runtime.server_url.removesuffix('/engines/vllm/v1')
        with httpx.Client(timeout=min(300, max(1, remaining_seconds())), trust_env=False, follow_redirects=False) as client:
            # Recheck the exact artifact and effective engine before content dispatch.
            from .model_service import Manager
            Manager('/unused', dmr=root).verify_backend(client, runtime.backend)
            metadata = client.get(root + '/models/' + runtime.model_id)
            metadata.raise_for_status()
            if metadata.json().get('id') != runtime.model_id:
                raise PDFError('PARSER_DMR_MODEL_MISMATCH')
            config = client.get(root + '/engines/_configure', params={'model': runtime.model_id})
            config.raise_for_status()
            if not any(row.get('Backend') == 'vllm' and row.get('ModelID') == runtime.model_id
                       and row.get('Config', {}).get('context-size') == self.model['context_size']
                       and (row.get('Config', {}).get('runtime-flags') or []) == dmr_flags(self.model, runtime.backend)
                       for row in config.json()):
                raise PDFError('PARSER_DMR_MODEL_MISMATCH')
            buffer = io.BytesIO()
            image.save(buffer, format='PNG')
            response = client.post(runtime.server_url + '/chat/completions', json={
                'model': runtime.model_id, 'messages': [{'role': 'user', 'content': [
                    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()}},
                    {'type': 'text', 'text': prompt}]}], 'temperature': 0, 'max_tokens': 8192,
                'chat_template_kwargs': {'enable_thinking': False}, 'stream': False})
            response.raise_for_status()
            body = response.json()
            if body.get('model') != runtime.model_id:
                raise PDFError('PARSER_DMR_MODEL_MISMATCH')
            choices = body.get('choices', [])
            if len(choices) != 1:
                raise PDFError('PARSER_OUTPUT_INVALID')
            message = choices[0].get('message', {})
            if message.get('role') != 'assistant' or message.get('tool_calls') or message.get('refusal'):
                raise PDFError('PARSER_OUTPUT_INVALID')
            return strip_fences(message.get('content'))


def teleocr_items(raw, page, image, infer):
    """TeleOCR's layout + crop recognition contract, preserving PDF coordinates."""
    from packages.ir import strict_loads
    raw = strip_fences(raw)
    if raw.startswith(('[', '{')):
        rows = strict_loads(raw)
    else:
        rows = []
        for line in raw.splitlines():
            match = re.fullmatch(r'<box:([\d\s]+)><label:(\w+)><([^>]+)>', line.strip())
            if not match:
                raise PDFError('PARSER_OUTPUT_INVALID')
            numbers = [int(v) for v in match[1].split()]
            if len(numbers) < 4 or len(numbers) % 2 or any(not 0 <= v <= 1000 for v in numbers):
                raise PDFError('PARSER_OUTPUT_INVALID')
            xs, ys = numbers[::2], numbers[1::2]
            rows.append({'type': match[2], 'bbox': [min(xs) / 1000, min(ys) / 1000, max(xs) / 1000, max(ys) / 1000],
                         'angle': next((v for tag, v in [('up', 0), ('right', 90), ('down', 180), ('left', 270)] if tag in match[3]), 0)})
    if isinstance(rows, dict):
        rows = rows.get('blocks', rows.get('layout'))
    if not isinstance(rows, list) or len(rows) > 1000:
        raise PDFError('PARSER_OUTPUT_INVALID')
    from .vlm_output import LABELS
    result = []
    width, height = image.size
    for entry in rows:
        if not isinstance(entry, dict):
            raise PDFError('PARSER_OUTPUT_INVALID')
        kind = entry.get('type', '')
        bounds = bbox(entry.get('bbox'), page, scale=1)
        x0, y0, x1, y1 = entry['bbox']
        label = LABELS.get(kind, LABELS.get(kind.replace('_', '-'), 'text'))
        if kind in ('image', 'figure', 'chart'):
            result.append(item('picture', '', bounds, page, len(result)))
            continue
        crop = image.crop((int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height)))
        try:
            if entry.get('angle') in (90, 180, 270):
                rotated = crop.rotate(-entry['angle'], expand=True)
                crop.close()
                crop = rotated
            prompt = ('This is the image of a table. Please output the table in OTSL format.' if kind == 'table' else
                      'Please write out the expression of the formula in the image using LaTeX format.' if 'equation' in kind else
                      'The image contains a code snippet, please output the parsing result.' if kind == 'code' else
                      'Please output the text content from the image.')
            text = strip_fences(infer(crop, prompt))
        finally:
            crop.close()
        if 'equation' in kind:
            label = 'formula'
        result.append(item(label, text, bounds, page, len(result), otsl_table(text) if kind == 'table' else None))
    return result


class VisionParser:
    def __init__(self, artifacts_path=None, inference_factory=None):
        self.artifacts_path = Path(artifacts_path or os.environ.get('DOCLING_ARTIFACTS_PATH', '/opt/docling/models'))
        self.inference_factory = inference_factory

    def parse(self, local_pdf, asset_id, output_dir, profile):
        if set(profile) - {'language', 'limits', 'created_at', 'parser_profile_revision'}:
            raise PDFError('PARSER_PROFILE_INVALID')
        selection = selected_profile(profile)
        if selection not in VLM_PROFILES:
            raise PDFError('PARSER_PROFILE_INVALID')
        from .progress import local_identity, report_progress
        runtime, model = runtime_config(selection), vlm_model(selection)
        require_device(runtime, selection)
        inspection = inspect_pdf(local_pdf, profile.get('limits'))
        report_progress('loading_model', model=local_identity(selection, vlm_lock()))
        factory = self.inference_factory or (DockerVision if runtime.device == 'dmr' else NativeVision)
        infer = factory(model, self.artifacts_path, runtime)
        report_progress('model_loaded', model=local_identity(selection, vlm_lock()))
        items, outputs = [], []
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(local_pdf) as pdf:
            for page in inspection['pages']:
                report_progress('page_started', page=page['page'], phase='model_inference')
                native = pdf[page['page'] - 1]
                try:
                    scale = min(2.0, (16_000_000 / (page['page_size'][0] * page['page_size'][1])) ** .5)
                    bitmap = native.render(scale=scale)
                    try:
                        image = bitmap.to_pil().convert('RGB')
                        try:
                            if selection == TELEOCR_PROFILE:
                                layout_image = image.resize((1036, 1036))
                                try:
                                    raw = strip_fences(infer(layout_image, PROMPTS[selection]))
                                finally:
                                    layout_image.close()
                            else:
                                raw = strip_fences(infer(image, PROMPTS[selection]))
                            outputs.append({'page': page['page'], 'output': raw})
                            try:
                                recognized = (teleocr_items(raw, page, image, infer) if selection == TELEOCR_PROFILE else
                                    html_items(raw, page) if model['output'] == 'html' else
                                    json_items(raw, page) if model['output'] == 'json' else markdown_items(raw, page))
                            except (PDFError, ValueError, TypeError, KeyError):
                                recognized = []
                                page['parse_failed'] = True
                                inspection.setdefault('warnings', []).append({'code': 'PARSER_PARTIAL_RESULT'})
                            items.extend(recognized)
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                finally:
                    native.close()
                page['ocr_attempted'] = True
                report_progress('page_completed', page=page['page'], phase='model_inference')
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / 'vision-parser.json').write_bytes(canonical_bytes({'profile': selection, 'revision': model['revision'], 'pages': outputs}))
        fingerprint = digest({'adapter': vlm_lock()['adapter_version'], 'model': model, 'prompt': PROMPTS[selection], **runtime.identity()})
        result = DoclingParser(self.artifacts_path).adapt(items, inspection, local_pdf, asset_id, output, profile=profile,
            parser_version=vlm_lock()['adapter_version'], parser_name=selection.removesuffix('-v1'),
            enrichment={'model': model['repo'], 'revision': model['revision']}, pipeline_hash=fingerprint)
        result['parser_profile_revision'] = selection
        return result
