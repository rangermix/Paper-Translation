"""Literal M0 rejection examples through actual IR and template validators."""
import copy
import hashlib
import json
from pathlib import Path
import re

import pytest
from packages.domain.errors import DomainError
from packages.ir import IRValidationError, block_hash, validate_ir
from packages.templates.registry import get_template

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('attack',['unknown-kind','non-pdf-locator','workspace-id','unreliable-math','external-svg','unsafe-link','other-instance-asset'])
def test_literal_ir_attack_is_rejected_before_publication(attack):
    ir=json.loads((ROOT/'fixtures/sample-document-v3.json').read_text('utf-8'))
    source=ir['source_revision']
    if attack=='unknown-kind':source['blocks'][0]['kind']='unsupported_interactive_widget'
    elif attack=='non-pdf-locator':source['blocks'][0]['provenance'][0]['type']='html'
    elif attack=='workspace-id':ir['document']['workspace_id']='hidden-default-workspace'
    elif attack=='unreliable-math':next(b for b in source['blocks'] if b['kind']=='math')['attributes']['representation']='model_guess_without_source'
    elif attack=='external-svg':source['assets'][1]['media_type']='image/svg+xml'
    elif attack=='other-instance-asset':source['assets'][1]['storage_key']='../other-instance/private.png'
    else:
        block=next(b for b in source['blocks'] if b['id']=='p1')
        # Keep text, atom count and hash internally coherent so URL rejection is exercised.
        block['source_inline'][0]={'type':'link','text':'The job has ','href':'javascript:window.evil=1'}
        block['source_hash']=block_hash(block,source['protected_atoms'])
        next(r for r in ir['translation_revision']['results'] if r['block_id']=='p1')['source_hash']=block['source_hash']
    with pytest.raises(IRValidationError):validate_ir(ir,asset_root=ROOT)


@pytest.mark.parametrize('attack',['one-color','css-import'])
def test_real_template_validation_rejects_changed_frozen_css_without_accepting_snapshot(monkeypatch,attack):
    original=Path.read_bytes
    css=ROOT/'res/reference/reader-v1.css';before=original(css)
    def changed(path):
        value=original(path)
        if path==css:
            if attack=='one-color':
                value,count=re.subn(rb'#[0-9a-fA-F]{6}',b'#123456',value,count=1)
                assert count==1
            else:value+=b'\n@import url(https://example.invalid/remote.css);'
        return value
    monkeypatch.setattr(Path,'read_bytes',changed)
    with pytest.raises(DomainError,match='Template hash mismatch'):get_template('reader-v1')
    assert hashlib.sha256(original(css)).hexdigest()==hashlib.sha256(before).hexdigest()
