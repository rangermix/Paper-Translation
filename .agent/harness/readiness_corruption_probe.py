"""Acceptance instance only: prove actual referenced PDF corruption breaks readiness."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import hashlib
import json
from pathlib import Path
import stat

from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.models import Document, SourceAsset
from packages.storage import safe_path
from smoke_library import request

BASE='http://127.0.0.1:8080'


def main():
    state=json.loads(Path('/evidence/offline-library.json').read_text())
    cfg=Config.load();db=Database(cfg)
    with db.transaction() as session:
        document=session.get(Document,state['document_id'])
        assert document.title=='Offline acceptance'
        asset=session.get(SourceAsset,document.source_asset_id)
        path=safe_path(cfg.data,asset.storage_key,must_exist=True)
        assert cfg.data.resolve()==Path('/data')
    original=path.read_bytes();mode=stat.S_IMODE(path.stat().st_mode)
    assert hashlib.sha256(original).hexdigest()==state['original_sha256']
    request(BASE,'GET','/health/ready')
    try:
        path.chmod(mode|stat.S_IWUSR)
        path.write_bytes(b'BROKEN'+original[6:])
        failure,_=request(BASE,'GET','/health/ready',expected=503)
        assert failure['error']['code']=='SOURCE_ASSET_CORRUPT',failure
    finally:
        path.write_bytes(original)
        path.chmod(mode)
    request(BASE,'GET','/health/ready')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==state['original_sha256']
    result={'status':'passed','scope':'fresh acceptance instance only','corrupt_pdf_readiness':503,
            'error':'SOURCE_ASSET_CORRUPT','restored_readiness':200,'original_bytes_restored':True}
    Path('/evidence/readiness-corruption.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':main()
