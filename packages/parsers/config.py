"""Reproducible CPU-only pipelines, with models supplied by the image."""
from packages.ir import digest
from .profiles import DEFAULT_PROFILE, GRANITE_PROFILE, GRANITE_MODEL, selected_profile

CPU_THREADS = 4
MEMORY_LIMIT_BYTES = 16 * 1024**3


def pipeline_fingerprint(lock, profile=DEFAULT_PROFILE):
    selected_profile({'parser_profile_revision': profile})
    if profile not in (DEFAULT_PROFILE, GRANITE_PROFILE):
        raise ValueError('PARSER_PROFILE_INVALID')
    if profile == GRANITE_PROFILE:
        return digest({'pipeline': lock.get('pipeline_revision'), 'profile': profile, 'models': lock,
            'device': 'cpu', 'threads': CPU_THREADS, 'dtype': 'float32', 'batch_size': 1,
            'scale': 2.0, 'force_backend_text': False, 'max_new_tokens': 8192})
    return digest({'pipeline': lock.get('pipeline_revision', 'legacy'), 'models': lock,
                   'device': 'cpu', 'threads': CPU_THREADS, 'ocr': 'rapidocr-onnxruntime',
                   'formula': True, 'code': True, 'table': 'accurate', 'vlm_dtype': 'float32',
                   'elements_batch_size': 1})


def pipeline_options(artifacts_path, lock, profile=DEFAULT_PROFILE):
    selected_profile({'parser_profile_revision': profile})
    if profile not in (DEFAULT_PROFILE, GRANITE_PROFILE):
        raise ValueError('PARSER_PROFILE_INVALID')
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_V2
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions, TableFormerMode
    from docling.datamodel.vlm_engine_options import TransformersVlmEngineOptions
    from docling.datamodel.settings import settings

    settings.perf.elements_batch_size = 1
    repos = {repo['repo_id']: repo for repo in lock['repositories']}
    if profile == GRANITE_PROFILE:
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        options = VlmPipelineOptions(artifacts_path=artifacts_path,
            enable_remote_services=False, allow_external_plugins=False,
            accelerator_options=AcceleratorOptions(num_threads=CPU_THREADS, device=AcceleratorDevice.CPU))
        options.vlm_options.model_spec = options.vlm_options.model_spec.model_copy(update={
            'default_repo_id': GRANITE_MODEL, 'revision': repos[GRANITE_MODEL]['revision'],
            'max_new_tokens': 8192, 'trust_remote_code': False})
        options.vlm_options.engine_options = TransformersVlmEngineOptions(
            device='cpu', torch_dtype='float32', compile_model=False)
        options.vlm_options.batch_size = 1
        options.vlm_options.scale = 2.0
        options.vlm_options.force_backend_text = False
        return options
    options = PdfPipelineOptions(artifacts_path=artifacts_path, do_ocr=True,
        do_table_structure=True, do_code_enrichment=True, do_formula_enrichment=True,
        enable_remote_services=False, allow_external_plugins=False,
        do_picture_classification=False, do_picture_description=False)
    options.ocr_options = RapidOcrOptions(backend='onnxruntime', force_full_page_ocr=False,
        rapidocr_params={'EngineConfig.onnxruntime.inter_op_num_threads': 1})
    options.layout_options.model_spec = DOCLING_LAYOUT_V2.model_copy(update={
        'revision': repos['docling-project/docling-layout-old']['revision']})
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.accelerator_options = AcceleratorOptions(num_threads=CPU_THREADS, device=AcceleratorDevice.CPU)
    options.code_formula_options.model_spec = options.code_formula_options.model_spec.model_copy(update={
        'revision': repos['docling-project/CodeFormulaV2']['revision']})
    # Compilation has a large cold-start cost; FP32 also works on CPUs without BF16 acceleration.
    options.code_formula_options.engine_options = TransformersVlmEngineOptions(
        device='cpu', torch_dtype='float32', compile_model=False)
    return options
