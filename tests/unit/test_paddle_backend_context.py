"""Paddle's deployment context survives DMR unload/reload and lost settings."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest


@pytest.mark.parametrize('limit,expected', [(None, '8192'), ('131072', '8192'), ('8192', '8192'), ('4096', '4096'),
    ('128K', '8192'), ('25.6k', '8192'), ('4K', '4K'), ('auto', '8192'), ('-1', '8192')])
@pytest.mark.parametrize('equals', [False, True])
def test_paddle_startup_caps_context_before_vllm_import(tmp_path, monkeypatch, limit, expected, equals):
    model = tmp_path / 'model'
    model.mkdir()
    (model/'config.json').write_text(json.dumps({'model_type': 'paddleocr_vl',
        'architectures': ['PaddleOCRVLForConditionalGeneration']}))
    args = ['python', '--model='+str(model)] if equals else ['python', '--model', str(model)]
    if limit:
        args += ['--max-model-len='+limit] if equals else ['--max-model-len', limit]
    monkeypatch.setattr(sys, 'argv', args)
    load_startup(tmp_path)
    assert option(sys.argv, '--max-model-len') == expected


@pytest.mark.parametrize('flags,expected', [
    (['--max-model-len', '8192', '--max-model-len', '131072'], '8192'),
    (['--max-model-len=4096', '--max-model-len=131072'], '8192'),
    (['--max-model-len', '131072', '--max-model-len=4096'], '4096'),
])
def test_last_runtime_flag_controls_effective_context(tmp_path, monkeypatch, flags, expected):
    model = tmp_path / 'model'
    model.mkdir()
    (model/'config.json').write_text(json.dumps({'model_type': 'paddleocr_vl',
        'architectures': ['PaddleOCRVLForConditionalGeneration']}))
    monkeypatch.setattr(sys, 'argv', ['python', '--model', str(model), *flags])
    load_startup(tmp_path)
    assert option(sys.argv, '--max-model-len') == expected


@pytest.mark.parametrize('config', [None, {}, {'model_type': 'gemma3'},
    {'model_type': 'paddleocr_vl', 'architectures': ['DifferentArchitecture']}])
def test_other_or_unidentified_models_keep_their_context(tmp_path, monkeypatch, config):
    model = tmp_path / 'model'
    model.mkdir()
    if config is not None:
        (model/'config.json').write_text(json.dumps(config))
    args = ['python', '--model', str(model), '--max-model-len', '131072']
    monkeypatch.setattr(sys, 'argv', args.copy())
    load_startup(tmp_path)
    assert sys.argv == args


def option(args, flag):
    for i in range(len(args) - 1, -1, -1):
        value = args[i]
        if value == flag:
            return args[i+1]
        if value.startswith(flag+'='):
            return value.split('=', 1)[1]


def load_startup(tmp_path):
    path = tmp_path / 'translation_startup.py'
    shutil.copyfile('deployment/local-translation-backend/translation_startup.py', path)
    path.with_name('translation_model_ids.json').write_text('[]')
    spec = importlib.util.spec_from_file_location('paddle_startup_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
