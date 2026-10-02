"""Importing the client must not load or require a model inference framework."""
import subprocess
import sys


def test_parser_startup_and_inspection_import_without_native_inference_modules():
    script = """
from workers.parser.main import ModelHealth
from packages.parsers.environment import detect_environment
from packages.parsers.pdf_vlm import VisionParser
import sys
assert detect_environment()['default'] == 'dmr'
assert not {'torch', 'transformers', 'paddle', 'paddleocr', 'docling', 'onnxruntime', 'cv2'} & set(sys.modules)
"""
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
