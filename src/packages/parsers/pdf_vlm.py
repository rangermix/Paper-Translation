"""Pinned full-page parsers using Docker Model Runner only."""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import httpx
from packages.ir import canonical_bytes, digest
from .catalog import vlm_lock, vlm_model
from .inspect import PDFError, inspect_pdf
from .source_adapter import SourceAdapter
from .profiles import (CHANDRA_PROFILE, INFINITY_FLASH_PROFILE, INFINITY_PRO_PROFILE,
                       SURYA_PROFILE, VLM_PROFILES, selected_profile)
from .runtime import runtime_config
from .vlm_output import html_items, json_items, strip_fences
from .semantic import VERSION as DECODER_VERSION
from .page_prompts import CHANDRA_LAYOUT_PROMPT

PROMPTS = {
    SURYA_PROFILE: 'OCR this image to HTML. Each block is a div with data-label and data-bbox (x0 y0 x1 y1, normalized 0-1000).',
    INFINITY_FLASH_PROFILE: '- Extract layout information from the provided PDF image.\n- For each layout element, output its bbox, category, and the text content within the bbox.\n- Bbox format: [x1, y1, x2, y2].\n- Allowed layout categories: [\'header\', \'title\', \'text\', \'figure\', \'table\', \'formula\', \'figure_caption\', \'table_caption\', \'formula_caption\', \'figure_footnote\', \'table_footnote\', \'page_footnote\', \'footer\'].\n- Text extraction and formatting:\n  1) For \'figure\', the text field must be an empty string.\n  2) For \'formula\', format text as LaTeX.\n  3) For \'table\', format text as HTML.\n  4) For all other categories (e.g., text, title), format text as Markdown.\n- The output text must be exactly the original text from the image, with no translation or rewriting.\n- Sort all layout elements in human reading order.\n- Final output must be a single JSON object.',
}
PROMPTS[INFINITY_PRO_PROFILE] = PROMPTS[INFINITY_FLASH_PROFILE]
PROMPTS[CHANDRA_PROFILE] = CHANDRA_LAYOUT_PROMPT
CONTRACT_REVISIONS = {
    SURYA_PROFILE: 'a2363d3311773a2b6145a40458043211c50c52f4',
    CHANDRA_PROFILE: 'd4f7467435aa4137d9539f000ddf0b7ced3eb43f',
    INFINITY_PRO_PROFILE: '9a93df02e725ee98ccd545d02580ec2c12c203ae',
    INFINITY_FLASH_PROFILE: '9a93df02e725ee98ccd545d02580ec2c12c203ae',
}


def response_evidence(value, runtime, model):
    """Injected offline inference has unknown completion/engine metadata."""
    if isinstance(value, str):
        return {'content': value, 'response': None, 'raw_response': None,
                'finish_reason': None, 'usage': None, 'engine_version': None,
                'model_artifact_id': runtime.model_id, 'backend': runtime.backend}
    if not isinstance(value, dict) or not isinstance(value.get('content'), str):
        raise PDFError('PARSER_OUTPUT_INVALID')
    return value


def decode_response(raw_response,runtime):
    """Keep unusable completions as evidence; a changed model identity is fatal."""
    from packages.ir import strict_loads
    result={'content':'','response':None,'raw_response':raw_response,'finish_reason':None,'usage':None,
        'model_artifact_id':runtime.model_id,'backend':runtime.backend,'engine_version':None}
    try:body=strict_loads(raw_response)
    except ValueError:return result|{'inference_error':'invalid_response_json'}
    result['response']=body
    if not isinstance(body,dict):return result|{'inference_error':'invalid_response_shape'}
    if body.get('model') != runtime.model_id:raise PDFError('PARSER_DMR_MODEL_MISMATCH')
    choices=body.get('choices',[])
    if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):return result|{'inference_error':'invalid_choices'}
    choice=choices[0];message=choice.get('message')
    result.update(finish_reason=choice.get('finish_reason') if isinstance(choice.get('finish_reason'),str) else None,usage=body.get('usage'))
    if not isinstance(message,dict) or message.get('role')!='assistant' or message.get('tool_calls') or message.get('refusal'):
        return result|{'inference_error':'unusable_message'}
    content=message.get('content')
    if not isinstance(content,str) or len(content)>1_000_000:return result|{'inference_error':'invalid_content'}
    return result|{'content':content}


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
            request = {
                'model': runtime.model_id, 'messages': [{'role': 'user', 'content': [
                    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()}},
                    {'type': 'text', 'text': prompt}]}], 'temperature': 0, 'max_tokens': 8192,
                'chat_template_kwargs': {'enable_thinking': False}, 'stream': False}
            # Read a bounded, non-SSE response. A large server response must not
            # first become an unbounded allocation in httpx.post().
            try:
                with client.stream('POST', runtime.server_url + '/chat/completions', json=request) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as error:
                        from .errors import inference_failure
                        return response_evidence('',runtime,self.model)|{'inference_error':type(error).__name__,
                            'inference_failure': inference_failure(error, runtime.backend)}
                    chunks = []
                    size = 0
                    for chunk in response.iter_bytes(chunk_size=65536):
                        size += len(chunk)
                        if size > 2_000_000:
                            raise PDFError('PARSER_OUTPUT_LIMIT')
                        chunks.append(chunk)
                    raw_response = b''.join(chunks).decode('utf-8')
            except httpx.HTTPError as error:
                from .errors import inference_failure
                return response_evidence('',runtime,self.model)|{'inference_error':type(error).__name__,
                    'inference_failure': inference_failure(error, runtime.backend)}
            return decode_response(raw_response,runtime)


class VisionParser:
    def __init__(self, artifacts_path=None, inference_factory=None):
        self.artifacts_path = Path(artifacts_path or os.environ.get('PARSER_MODEL_CACHE', '/model_cache'))
        self.inference_factory = inference_factory

    def parse(self, local_pdf, asset_id, output_dir, profile):
        if set(profile) - {'language', 'limits', 'created_at', 'parser_profile_revision'}:
            raise PDFError('PARSER_PROFILE_INVALID')
        selection = selected_profile(profile)
        if selection not in VLM_PROFILES:
            raise PDFError('PARSER_PROFILE_INVALID')
        from .progress import local_identity, report_progress
        runtime, model = runtime_config(selection), vlm_model(selection)
        inspection = inspect_pdf(local_pdf, profile.get('limits'))
        report_progress('loading_model', model=local_identity(selection, vlm_lock()))
        factory = self.inference_factory or DockerVision
        infer = factory(model, self.artifacts_path, runtime)
        report_progress('model_loaded', model=local_identity(selection, vlm_lock()))
        items, outputs = [], []
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        evidence = {'decoder_version': DECODER_VERSION, 'contract_revision': CONTRACT_REVISIONS[selection],
            'backend': runtime.backend, 'engine_version': None,
            'preprocessing': 'PDFium RGB PNG; scale<=2; page<=16M pixels; top-left 0-1000 layout rectangles', 'pages': []}
        from packages.storage import atomic_write
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
                            envelope = response_evidence(infer(image, PROMPTS[selection]), runtime, model)
                            raw = envelope['content']
                            record = {'page': page['page'], 'profile': selection, 'revision': model['revision'],
                                'decoder_version': DECODER_VERSION, 'contract_revision': CONTRACT_REVISIONS[selection], 'page_size': page['page_size'],
                                'render_size': list(image.size), 'prompt_sha256': digest(PROMPTS[selection].encode()), **envelope}
                            # Literal paths index this decoder input by Unicode
                            # code point; DOM paths refer to its repaired tree.
                            record['decoder_payload'] = strip_fences(raw) if len(raw)<=1_000_000 else None
                            key = f'evidence/page-{page["page"]:04d}.response.json'
                            encoded = canonical_bytes(record)
                            if len(encoded) > 6_000_000 or sum(p['byte_size'] for p in evidence['pages']) + len(encoded) > 80_000_000:
                                raise PDFError('PARSER_OUTPUT_LIMIT')
                            atomic_write(output, key, encoded)
                            evidence['pages'].append({'page': page['page'], 'path': key, 'sha256': digest(encoded),
                                'byte_size': len(encoded), 'finish_reason': envelope['finish_reason'][:40] if isinstance(envelope.get('finish_reason'),str) else None})
                            outputs.append({'page': page['page'], 'response_path': key, 'sha256': digest(encoded)})
                            # Update the manifest before attempting to decode this page.
                            # This index is a checkpoint in this fenced staging
                            # directory. Page receipts and promoted files stay immutable.
                            atomic_write(output, 'vision-parser.json', canonical_bytes({'profile': selection, 'revision': model['revision'], 'pages': outputs}), immutable=False)
                            if envelope.get('inference_failure'):
                                from .errors import safe_failure
                                error = safe_failure(envelope['inference_failure'])
                                raise PDFError(error['code'], error['message'],
                                    {**error.get('details', {}), 'page': page['page']})
                            diagnostics = []
                            if envelope.get('inference_error'):
                                page['parse_failed']=True
                                diagnostics.append({'code':'MODEL_PAGE_FAILED','output_path':'/','reason':str(envelope['inference_error'])[:500]+'; original page retained; no automatic retry'})
                            if envelope.get('finish_reason') not in {None, 'stop'}:
                                diagnostics.append({'code': 'PARSER_OUTPUT_INCOMPLETE', 'output_path': '/',
                                    'reason': ('Inference ended with ' + str(envelope['finish_reason']))[:500]})
                            try:
                                recognized = html_items(raw, page, diagnostics) if model['output'] == 'html' else json_items(raw, page, diagnostics)
                            except (PDFError, ValueError, TypeError, KeyError):
                                recognized = []
                                page['parse_failed'] = True
                                inspection.setdefault('warnings', []).append({'code': 'PARSER_PARTIAL_RESULT'})
                            if diagnostics:
                                page['decoder_diagnostics'] = diagnostics
                                inspection.setdefault('warnings', []).extend({'page': page['page'], **d} for d in diagnostics)
                            atomic_write(output, f'evidence/page-{page["page"]:04d}.decode.json', canonical_bytes({'page': page['page'], 'diagnostics': diagnostics}))
                            items.extend(recognized)
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                finally:
                    native.close()
                page['ocr_attempted'] = True
                report_progress('page_completed', page=page['page'], phase='model_inference')
        fingerprint = digest({'adapter': vlm_lock()['adapter_version'], 'decoder': DECODER_VERSION,
            'schema': '4.0', 'model': model, 'contract_revision': CONTRACT_REVISIONS[selection], 'prompt': PROMPTS[selection], 'max_tokens': 8192,
            'preprocessing': evidence['preprocessing'], **runtime.identity()})
        result = SourceAdapter().adapt(items, inspection, local_pdf, asset_id, output, profile=profile,
            parser_version=vlm_lock()['adapter_version'], parser_name=selection.removesuffix('-v1'),
            enrichment={'model': model['repo'], 'revision': model['revision']}, pipeline_hash=fingerprint,
            model_generated_source=True, semantic=True, parser_evidence=evidence)
        result['parser_profile_revision'] = selection
        return result
