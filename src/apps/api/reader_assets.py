"""Shared, content-addressed copies of the fonts shipped with reader templates."""
from pathlib import PurePosixPath

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

from packages.domain.errors import DomainError, require
from packages.paths import ROOT
from packages.storage import file_hash, safe_path
from packages.templates.registry import list_templates

router = APIRouter()


def registered_font(sha256: str, filename: str):
    # Only public vendor fonts may share a cache across documents. Request paths
    # never select filesystem paths, document content, or arbitrary template files.
    return next((asset for template in list_templates() for asset in template.get('extra_assets', [])
        if asset['media_type'] == 'font/woff2' and asset['sha256'] == sha256
        and PurePosixPath(asset['path']).name == filename), None)


def font_url(asset):
    return f'/reader-assets/fonts/{asset["sha256"]}/{PurePosixPath(asset["path"]).name}'


@router.get('/reader-assets/fonts/{sha256}/{filename}')
@router.head('/reader-assets/fonts/{sha256}/{filename}', include_in_schema=False)
def reader_font(sha256: str, filename: str, request: Request):
    asset = registered_font(sha256, filename)
    require(asset is not None, 'NOT_FOUND', status=404)
    try:
        path = safe_path(ROOT, asset['source'], must_exist=True)
        require(file_hash(path) == sha256, 'READER_FONT_CORRUPT', status=409)
    except (DomainError, OSError, ValueError) as exc:
        raise DomainError('READER_FONT_CORRUPT', status=409) from exc
    headers = {'ETag': f'"{sha256}"', 'Cache-Control': 'public, max-age=31536000, immutable'}
    # FileResponse supplies validators but does not evaluate conditional requests.
    validators = [value.strip().removeprefix('W/') for value in request.headers.get('If-None-Match', '').split(',')]
    if '*' in validators or headers['ETag'] in validators:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type=asset['media_type'], headers=headers)
