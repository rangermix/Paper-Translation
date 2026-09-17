"""Read-only model manifest validation; this module never downloads weights."""
from pathlib import Path
import hashlib
from packages.ir import safe_path, strict_loads
from .inspect import PDFError
from packages.paths import ROOT

LOCK_PATH = ROOT/'deployment/parser-models.lock.json'


def parser_version(profile='docling-v1'):
    from .profiles import PADDLE_PROFILE, selected_profile
    selected_profile({'parser_profile_revision': profile})
    return strict_loads(LOCK_PATH.read_bytes())['paddleocr_version' if profile == PADDLE_PROFILE else 'docling_version']


def verify_models(artifacts_path):
    root = Path(artifacts_path)
    if not root.is_dir():
        raise PDFError('PARSER_MODELS_MISSING')
    lock = strict_loads(LOCK_PATH.read_bytes())
    try:
        for repo in lock['repositories']:
            for entry in repo['files']:
                file = safe_path(root,repo['local_directory']+'/'+entry['path'])
                with file.open('rb') as handle:
                    if file.stat().st_size != entry['byte_size'] or hashlib.file_digest(handle,'sha256').hexdigest() != entry['sha256']:
                        raise PDFError('PARSER_MODEL_HASH_MISMATCH')
    except PDFError:
        raise
    except (OSError,ValueError) as exc:
        raise PDFError('PARSER_MODELS_MISSING') from exc
    return lock
