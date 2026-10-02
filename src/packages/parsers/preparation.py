"""Parser child control client; only a profile/backend leaves before inference."""
from pathlib import Path
import time

import httpx
from packages.ir import safe_path
from .catalog import download_spec, vlm_model
from .download import valid
from .inspect import PDFError
from .model_service import CONTROL_URL, PREPARATION_FAILURE_CODES
from .profiles import VLM_PROFILES


def prepare_models(profile, root, runtime):
    from .progress import remaining_seconds, report_progress
    backend = runtime.backend
    report_progress('loading_model', phase='model_preparation')
    try:
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = client.post(CONTROL_URL + '/models/' + profile + '/prepare', params={'backend': backend})
            response.raise_for_status()
            while remaining_seconds() > 0:
                response = client.get(CONTROL_URL + '/models/' + profile, params={'backend': backend})
                response.raise_for_status()
                data = response.json()
                if data.get('status') == 'ready':
                    verify_cached_models(profile, root)
                    return
                if data.get('status') == 'failed':
                    code = data.get('code', '')
                    raise PDFError(code if code in PREPARATION_FAILURE_CODES else 'PARSER_MODEL_PREPARATION_FAILED')
                time.sleep(min(1, remaining_seconds()))
    except PDFError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        raise PDFError('PARSER_MODEL_PREPARATION_FAILED') from exc
    raise PDFError('PARSER_TIMEOUT')


def verify_cached_models(profile, root):
    try:
        for spec in download_spec(profile):
            if not valid(safe_path(root, spec['path']), spec):
                raise PDFError('PARSER_MODEL_HASH_MISMATCH')
    except PDFError:
        raise
    except (OSError, ValueError) as exc:
        raise PDFError('PARSER_MODELS_MISSING') from exc


def model_directory(profile, root):
    if profile not in VLM_PROFILES:
        raise PDFError('PARSER_PROFILE_INVALID')
    model = vlm_model(profile)
    return Path(root) / model['repo'].replace('/', '--') / model['revision']
