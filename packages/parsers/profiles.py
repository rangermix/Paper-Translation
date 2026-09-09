"""Public local parser profiles; safe to import without model dependencies."""
from typing import Literal

ParserProfile = Literal['docling-v1', 'granite-docling-v1', 'paddleocr-vl-1.6-v1']
DEFAULT_PROFILE: ParserProfile = 'docling-v1'
GRANITE_PROFILE: ParserProfile = 'granite-docling-v1'
GRANITE_MODEL = 'ibm-granite/granite-docling-258M'
PADDLE_PROFILE: ParserProfile = 'paddleocr-vl-1.6-v1'
PADDLE_MODEL = 'PaddlePaddle/PaddleOCR-VL-1.6'
PARSER_PROFILES = (
    {'id': DEFAULT_PROFILE, 'label': 'Docling 标准', 'device': 'cpu',
     'description': '原生文本、OCR、表格及公式 / 代码增强。'},
    {'id': GRANITE_PROFILE, 'label': 'Granite Docling 258M', 'device': 'cpu',
     'description': '本地视觉模型逐页识别文字与版面；CPU 解析较慢。'},
    {'id': PADDLE_PROFILE, 'label': 'PaddleOCR-VL-1.6', 'device': 'cpu',
     'description': '官方 PaddleOCR 套件识别文字、版面与表格结构；CPU 解析较慢。'},
)


def selected_profile(profile):
    value = profile.get('parser_profile_revision', DEFAULT_PROFILE)
    if value not in (DEFAULT_PROFILE, GRANITE_PROFILE, PADDLE_PROFILE):
        raise ValueError('PARSER_PROFILE_INVALID')
    return value
