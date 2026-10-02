"""Archived native inference; see the archive restoration notes."""
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
