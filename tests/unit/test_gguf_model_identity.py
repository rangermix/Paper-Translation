"""DMR's exact GGUF bundle name is an identity receipt, not an arbitrary alias."""
import httpx
import pytest

from packages.local_models.catalog import artifact, get_model
from packages.providers.connection import TEST_UNIT
from packages.providers.local_translation import LocalTranslation
from tests.unit.test_local_translation_provider import profile


@pytest.mark.parametrize('variant', ['exact_bundle', 'other_digest', 'other_file', 'foreign_prefix'])
def test_gguf_bundle_response_requires_exact_digest_filename_and_root(variant):
    model = get_model('hy-mt2-7b-q4-k-m-gguf'); ident = artifact(model)['id']
    reported = '/models/bundles/sha256/' + ident.split(':')[1] + '/model/' + model['files'][0]['path']
    if variant == 'other_digest':
        reported = reported.replace(ident.split(':')[1], '0' * 64)
    elif variant == 'other_file':
        reported = reported.replace(model['files'][0]['path'], 'other-model.gguf')
    elif variant == 'foreign_prefix':
        reported = '/unverified' + reported
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
        'model': reported, 'choices': [{'text': '本地译文', 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 20, 'completion_tokens': 5}}))
    result = LocalTranslation(transport=transport).translate([TEST_UNIT], profile(model['id']), [])
    if variant == 'exact_bundle':
        assert result['status'] == 'completed' and result['response_model'] == ident
        assert result['reported_model_id'] == reported
        assert result['usage'] == {'input_tokens': 20, 'output_tokens': 5}
    else:
        assert result['failure_code'] == 'PROVIDER_MODEL_MISMATCH'
        assert result['response_model'] == reported
