"""Inside maintenance: corrupt only a fresh copy of our own acceptance backup."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import json
from pathlib import Path
import shutil
import uuid

from sqlalchemy import select
from packages.domain.config import Config
from packages.domain.db import Database
from packages.domain.errors import DomainError
from packages.domain.models import Document, Settings
from packages.ir import digest
from packages.maintenance.__main__ import restore, verify_backup
from packages.storage import safe_path


def state(db):
    with db.transaction() as session:
        settings=session.get(Settings,'singleton')
        return {'documents':sorted((d.id,d.title,d.generation) for d in session.scalars(select(Document))),
                'maintenance':settings.maintenance,'dispatch_disabled':settings.dispatch_disabled}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--backup-id',required=True)
    args=parser.parse_args()
    backups=Path('/backups')
    original,_=verify_backup(backups,args.backup_id)
    clone_id='acceptance-corrupt-'+uuid.uuid4().hex
    clone=safe_path(backups,clone_id)
    assert backups.resolve()==Path('/backups') and clone.parent==backups and not clone.exists()
    shutil.copytree(original,clone)
    # Simulate storage corruption of an otherwise valid backup dump.
    with (clone/'database.dump').open('ab') as output:output.write(b'CORRUPTED ACCEPTANCE COPY')
    cfg=Config.load();db=Database(cfg)
    before=state(db)
    try:
        restore(db,cfg,backups,clone_id,replace=True)
    except DomainError as error:
        assert error.code=='BACKUP_CORRUPT',error.code
    else:
        raise AssertionError('Corrupt backup was accepted')
    after=state(db)
    assert before==after,'Validation failure changed library or maintenance state'
    verify_backup(backups,args.backup_id)
    print(json.dumps({'status':'passed','rejected_code':'BACKUP_CORRUPT',
        'library_state_unchanged':True,'library_state_hash':digest(before),
        'valid_original_backup_unchanged':True,'corrupted_copy':clone_id}))


if __name__=='__main__':main()
