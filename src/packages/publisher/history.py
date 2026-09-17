from sqlalchemy import select

from packages.domain.db import get_document
from packages.domain.errors import DomainError, require
from packages.domain.models import Artifact, Job, Publication, Task, new_id
from packages.ir import digest
from packages.publisher import verify_artifact
from packages.storage import safe_path


def checked_manifest(config, artifact):
    try:
        manifest = verify_artifact(safe_path(config.data, artifact.storage_key))
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise DomainError('ARTIFACT_CORRUPT', status=409) from error
    require(digest(manifest) == artifact.manifest_hash, 'ARTIFACT_CORRUPT')
    return manifest


def commit_publication(session, config, edition, artifact, expected_generation, operation, origin='manual_ui'):
    get_document(session, edition.document_id, lock=True)
    require(edition.generation == expected_generation, 'PRECONDITION_FAILED', status=412)
    if artifact:
        require(artifact.document_id == edition.document_id and artifact.edition_id == edition.id and artifact.state == 'verified', 'ARTIFACT_MISMATCH')
        manifest = checked_manifest(config, artifact)
        require(manifest.get('mode', 'release') == 'release', 'DRAFT_ARTIFACT')
    edition.current_artifact_id = artifact.id if artifact else None
    edition.generation += 1
    session.add(Publication(id=new_id('publication'), edition_id=edition.id, artifact_id=edition.current_artifact_id,
        generation=edition.generation, operation=operation, origin=origin))
    if artifact:
        job = Job(id=new_id('job'), document_id=edition.document_id, stage='index', payload={'edition_id': edition.id, 'generation': edition.generation})
        session.add(job)
        session.flush()
        session.add(Task(id=new_id('task'), job_id=job.id, kind='index', payload=job.payload))
    return edition
