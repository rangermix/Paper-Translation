import pytest

from packages.parsers.progress import configure_progress, read_progress, report_progress, reset_progress


def test_progress_survives_partial_write_and_rejects_other_fence(tmp_path):
    request = {'task_id': 'task_test', 'fence': 1, 'source_sha256': 'a' * 64, 'max_pages': 3}
    token = configure_progress(tmp_path, request)
    report_progress('page_started', page=2)
    reset_progress(token)
    events = read_progress(tmp_path, request)
    assert events[0]['page'] == 2
    assert read_progress(tmp_path, request, 1) == []
    with (tmp_path / 'progress.jsonl').open('ab') as handle:
        handle.write(b'{"incomplete":')
    assert len(read_progress(tmp_path, request)) == 1
    with pytest.raises(ValueError, match='BINDING'):
        read_progress(tmp_path, request | {'fence': 2})


def test_new_model_history_preserves_timeout_without_inventing_dmr_version(tmp_path, monkeypatch):
    from packages.parsers.catalog import vlm_lock
    from packages.parsers.progress import local_identity
    request = {'task_id': 'task_test', 'fence': 1, 'source_sha256': 'a' * 64, 'max_pages': 3,
               'timeout_seconds': 3600}
    token = configure_progress(tmp_path, request)
    try:
        monkeypatch.setenv('PARSER_ACCELERATOR', 'dmr')
        model = local_identity('surya-ocr-2-v1', vlm_lock())
        assert model['engine_version'] is None and model['timeout_seconds'] == 3600
        monkeypatch.setenv('PARSER_ACCELERATOR', 'cpu')
        model = local_identity('teleocr-v1', vlm_lock())
        assert model['engine_version'] == '4.57.1' and model['timeout_seconds'] == 3600
    finally:
        reset_progress(token)
