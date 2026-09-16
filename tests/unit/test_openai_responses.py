import json
import httpx
import pytest
from packages.providers.openai_responses import OpenAIResponses,ENDPOINT
from packages.providers.contract import ProviderFailure

PROFILE={'model_id':'fixture-model','max_input_tokens':16384,'max_output_tokens':128}
UNIT={'unit_id':'a:0','source_language':'en','target_locale':'zh-Hans','source_inline':[{'type':'text','text':'Hello'}],'protected_atoms':{},'context':{}}


def test_official_endpoint_strict_format_no_tools_no_store(tmp_path):
    key=tmp_path/'key';key.write_text('test-only-key')
    calls=[]
    def handler(request):
        calls.append(request);body=json.loads(request.content)
        assert str(request.url)==ENDPOINT and body['store'] is False and body['tools']==[]
        assert body['text']['format']['strict'] is True and body['truncation']=='disabled'
        assert request.headers['authorization']=='Bearer test-only-key'
        return httpx.Response(200,json={'id':'response-fixture','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"results":[]}'}]}],'usage':{'input_tokens':1,'output_tokens':2}},headers={'x-request-id':'request-fixture'})
    result=OpenAIResponses(key,httpx.MockTransport(handler)).translate([UNIT],PROFILE,[])
    assert result['request_id']=='request-fixture' and len(calls)==1


def test_read_timeout_is_unknown_without_implicit_retry(tmp_path):
    key=tmp_path/'key';key.write_text('test-only-key');calls=[]
    def handler(request):calls.append(request);raise httpx.ReadTimeout('simulated after execution')
    with pytest.raises(ProviderFailure) as exc:OpenAIResponses(key,httpx.MockTransport(handler)).translate([UNIT],PROFILE,[])
    assert exc.value.outcome=='unknown' and len(calls)==1


def test_401_stops_configuration(tmp_path):
    key=tmp_path/'key';key.write_text('test-only-key')
    with pytest.raises(ProviderFailure) as exc:OpenAIResponses(key,httpx.MockTransport(lambda r:httpx.Response(401))).translate([UNIT],PROFILE,[])
    assert exc.value.code=='PROVIDER_CONFIG' and exc.value.outcome=='not_executed'


@pytest.mark.parametrize('tracking,expected', [(None,None), ('',None), ('r'*201,None),
    ('\x00',None), ('\n',None), ({},None), (5,None), (True,None), ('valid-request-id','valid-request-id'), ('r'*200,'r'*200)])
def test_tracking_id_is_optional_bounded_evidence(tracking,expected):
    value={'id':tracking,'status':'completed','output':[],
        'usage':{'input_tokens':1,'output_tokens':2}}
    provider=OpenAIResponses(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=value)),auth_mode='none')
    result=provider.translate([UNIT],PROFILE|{'auth_mode':'none'},[])
    assert result['request_id']==expected and result['usage']==value['usage']
