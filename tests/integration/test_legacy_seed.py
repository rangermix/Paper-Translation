from pathlib import Path
import json
import re
import zipfile
import pytest
from sqlalchemy import select,func
from packages.domain.models import Document,Artifact,SourceRevision,TranslationRevision,ReviewRecord
from packages.seed.legacy import seed_legacy
from packages.publisher import verify_artifact,export_bundle,export_single_html

pytestmark=pytest.mark.postgres
ROOT=Path(__file__).resolve().parents[2]


def test_known_legacy_seed_is_idempotent_and_not_fake_ir(database,tmp_path):
    db,cfg=database
    first=seed_legacy(db,cfg);second=seed_legacy(db,cfg)
    assert first['created']==2 and second['created']==0
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Document))==2
        assert session.scalar(select(func.count()).select_from(SourceRevision))==0
        assert session.scalar(select(func.count()).select_from(TranslationRevision))==0
        assert session.scalar(select(func.count()).select_from(ReviewRecord))==0
        artifacts=session.scalars(select(Artifact)).all()
    for artifact in artifacts:
        root=cfg.data/artifact.storage_key;manifest=verify_artifact(root)
        frozen=(ROOT/manifest['legacy_source_path']).read_bytes()
        assert (root/'legacy-original.html').read_bytes()==frozen
        expected=frozen.replace(b'<a href="../index.html">',b'<a href="/">',1)
        assert (root/'index.html').read_bytes()==expected
        assert re.search(rb'<style>(.*?)</style>',expected,re.S).group(1)==re.search(rb'<style>(.*?)</style>',frozen,re.S).group(1)
        output=export_single_html(root,tmp_path/(artifact.id+'.html')).read_text('utf-8')
        assert 'data:image/png;base64,' in output and 'href="/"' not in output and 'href="source/' not in output
        bundle=export_bundle(root,tmp_path/(artifact.id+'.zip'))
        with zipfile.ZipFile(bundle) as archive:
            assert not any(name.endswith('.pdf') for name in archive.namelist())
            assert 'legacy-original.html' not in archive.namelist()
