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
