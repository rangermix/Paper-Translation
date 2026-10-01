"""Public local parser profiles; safe to import without model dependencies."""
from typing import Literal

ParserProfile = Literal['docling-v1', 'granite-docling-v1', 'paddleocr-vl-1.6-v1',
    'surya-ocr-2-v1', 'chandra-ocr-2-v1', 'infinity-parser2-pro-v1',
    'infinity-parser2-flash-v1', 'teleocr-v1', 'xiaomi-ocr-0-v1']
DOCLING_PROFILE: ParserProfile = 'docling-v1'
GRANITE_PROFILE: ParserProfile = 'granite-docling-v1'
GRANITE_MODEL = 'ibm-granite/granite-docling-258M'
PADDLE_PROFILE: ParserProfile = 'paddleocr-vl-1.6-v1'
DEFAULT_PROFILE: ParserProfile = PADDLE_PROFILE
PADDLE_MODEL = 'PaddlePaddle/PaddleOCR-VL-1.6'
SURYA_PROFILE = 'surya-ocr-2-v1'
CHANDRA_PROFILE = 'chandra-ocr-2-v1'
INFINITY_PRO_PROFILE = 'infinity-parser2-pro-v1'
INFINITY_FLASH_PROFILE = 'infinity-parser2-flash-v1'
TELEOCR_PROFILE = 'teleocr-v1'
XIAOMI_PROFILE = 'xiaomi-ocr-0-v1'
VLM_PROFILES = (SURYA_PROFILE, CHANDRA_PROFILE, INFINITY_PRO_PROFILE,
                INFINITY_FLASH_PROFILE, TELEOCR_PROFILE, XIAOMI_PROFILE)
DMR_PROFILES = tuple(p for p in VLM_PROFILES if p != TELEOCR_PROFILE)
NATIVE_PROFILES = (DOCLING_PROFILE, GRANITE_PROFILE, PADDLE_PROFILE,
                  *(p for p in VLM_PROFILES if p != INFINITY_PRO_PROFILE))
PARSER_PROFILES = (
    {'id': DOCLING_PROFILE, 'label': 'Docling 标准', 'devices': ['cpu', 'cuda'],
     'description': '原生文本、OCR、表格及公式 / 代码增强。'},
    {'id': GRANITE_PROFILE, 'label': 'Granite Docling 258M', 'devices': ['cpu', 'cuda'],
     'description': '本地视觉模型逐页识别文字与版面。'},
    {'id': PADDLE_PROFILE, 'label': 'PaddleOCR-VL-1.6', 'devices': ['cpu', 'cuda', 'mlx'],
     'description': '官方 PaddleOCR 套件识别文字、版面与表格结构。'},
    {'id': SURYA_PROFILE, 'label': 'Surya OCR 2', 'devices': ['cpu', 'cuda', 'dmr'],
     'description': '0.65B 视觉模型识别文字、版面、公式与表格。'},
    {'id': CHANDRA_PROFILE, 'label': 'Chandra OCR 2', 'devices': ['cpu', 'cuda', 'dmr'],
     'description': '4B 视觉模型识别复杂表格、手写与多语种内容；权重约 10.6 GB。'},
    {'id': INFINITY_PRO_PROFILE, 'label': 'Infinity-Parser2 Pro', 'devices': ['dmr'],
     'description': '35.1B 高精度方案；约 70.2 GB 权重，需要足够内存的 Docker Model Runner。'},
    {'id': INFINITY_FLASH_PROFILE, 'label': 'Infinity-Parser2 Flash', 'devices': ['cpu', 'cuda', 'dmr'],
     'description': '2B 低延迟方案，输出阅读顺序、文字、表格与公式。'},
    {'id': TELEOCR_PROFILE, 'label': 'TeleOCR', 'devices': ['cpu', 'cuda'],
     'description': '1.5B 文档识别；使用锁定的自定义 Transformers 模型。'},
    {'id': XIAOMI_PROFILE, 'label': 'Xiaomi-OCR-0', 'devices': ['cpu', 'cuda', 'dmr'],
     'description': '0.8B 轻量文档识别，保留原始页图与内容核对提示。'},
)
PROFILE_IDS = tuple(p['id'] for p in PARSER_PROFILES)


def selected_profile(profile):
    value = profile.get('parser_profile_revision', DOCLING_PROFILE)
    if value not in PROFILE_IDS:
        raise ValueError('PARSER_PROFILE_INVALID')
    return value


def preferred_profile(preferences):
    """New work uses Paddle; missing historical snapshots retain Docling."""
    return selected_profile({'parser_profile_revision': DEFAULT_PROFILE} | preferences)
