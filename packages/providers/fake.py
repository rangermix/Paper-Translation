"""Explicit test double; production provider construction never chooses this class."""
import copy
from packages.ir import canonical_bytes
from .contract import ProviderFailure


class FakeProvider:
    def __init__(self,script=None):self.script=list(script or []);self.calls=[]
    def translate(self,units,profile,glossary):
        self.calls.append(copy.deepcopy(units))
        step=self.script.pop(0) if self.script else 'echo'
        if isinstance(step,Exception):raise step
        output={'results':[{'unit_id':u['unit_id'],'target_inline':copy.deepcopy(u['source_inline'])} for u in reversed(units)]}
        if callable(step):output=step(units)
        return {'request_id':'fake-request-'+str(len(self.calls)),'usage':{'input_tokens':100,'output_tokens':50},'status':'completed','refusal':False,'output_text':canonical_bytes(output).decode(),'response_model':'fake'}

    def review(self,units,profile,glossary):
        response=self.translate(units,profile,glossary)
        response['output_text']='{"issues":[]}'
        return response
