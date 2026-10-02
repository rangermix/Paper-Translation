"""Active full-page DMR parsers and separate, read-only historical identities."""
from typing import Literal

ParserProfile = Literal['surya-ocr-2-v1', 'chandra-ocr-2-v1',
                        'infinity-parser2-pro-v1', 'infinity-parser2-flash-v1']
SURYA_PROFILE = 'surya-ocr-2-v1'
CHANDRA_PROFILE = 'chandra-ocr-2-v1'
INFINITY_PRO_PROFILE = 'infinity-parser2-pro-v1'
INFINITY_FLASH_PROFILE = 'infinity-parser2-flash-v1'
DEFAULT_PROFILE = SURYA_PROFILE
PARSER_PROFILES = (
    {'id': SURYA_PROFILE, 'label': 'Surya OCR 2', 'devices': ['dmr'],
     'description': '0.65B 全页视觉解析；通过 Docker Model Runner 运行。'},
    {'id': CHANDRA_PROFILE, 'label': 'Chandra OCR 2', 'devices': ['dmr'],
     'description': '4B 全页解析，支持复杂表格、手写与多语种；权重约 10.6 GB。'},
    {'id': INFINITY_PRO_PROFILE, 'label': 'Infinity-Parser2 Pro', 'devices': ['dmr'],
     'description': '35.1B 全页解析；约 70.2 GB 权重，需要足够后端内存。'},
    {'id': INFINITY_FLASH_PROFILE, 'label': 'Infinity-Parser2 Flash', 'devices': ['dmr'],
     'description': '2B 全页解析，输出文字、阅读顺序、表格与公式。'},
)
PROFILE_IDS = tuple(row['id'] for row in PARSER_PROFILES)
VLM_PROFILES = DMR_PROFILES = PROFILE_IDS
RETIRED_PROFILES = {
    'docling-v1': {'label': 'Docling 标准', 'status': 'removed'},
    'granite-docling-v1': {'label': 'Granite Docling 258M', 'status': 'removed'},
    'paddleocr-vl-1.6-v1': {'label': 'PaddleOCR-VL-1.6', 'status': 'archived'},
    'xiaomi-ocr-0-v1': {'label': 'Xiaomi-OCR-0', 'status': 'archived'},
    'teleocr-v1': {'label': 'TeleOCR', 'status': 'archived'},
}


def recorded_profile(snapshot):
    """Missing old job choices mean the former default, never today's default."""
    value = snapshot.get('parser_profile_revision', 'docling-v1')
    if value not in PROFILE_IDS and value not in RETIRED_PROFILES:
        raise ValueError('PARSER_PROFILE_INVALID')
    return value


def selected_profile(profile):
    value = profile.get('parser_profile_revision', DEFAULT_PROFILE)
    if value in RETIRED_PROFILES:
        raise ValueError('PARSER_PROFILE_UNAVAILABLE')
    if value not in PROFILE_IDS:
        raise ValueError('PARSER_PROFILE_INVALID')
    return value


def preferred_profile(preferences):
    """Reading saved settings preserves inactive choices without enabling them."""
    return recorded_profile(preferences) if 'parser_profile_revision' in preferences else DEFAULT_PROFILE
