import logging
from datetime import timedelta
import os
from pathlib import Path
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from packages.domain.config import Config, provider_profile
from packages.domain.db import Database, SCHEMA_VERSION
from packages.domain.errors import DomainError
from packages.domain.models import Heartbeat, now
from packages.ir import strict_loads
from packages.storage import safe_path
from .library import router as library_router


def create_app(config=None, database=None):
    cfg = config or Config.load()
    app = FastAPI(title='Bilingual Personal PDF Library', version='0.1.0')
    app.state.config = cfg
    app.state.db = database or (Database(cfg) if cfg.database_url else None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(cfg.allowed_hosts))

    @app.middleware('http')
    async def request_boundary(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            same_site = request.headers.get('sec-fetch-site')
            if (origin and origin not in cfg.origins) or same_site == 'cross-site' or request.headers.get('x-library-request') != '1':
                return error_response(request, DomainError('ORIGIN_REJECTED', status=403))
            if os.environ.get('READ_ONLY', 'false').lower() == 'true':
                return error_response(request, DomainError('MAINTENANCE', status=503))
            if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() == 'application/json':
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    limit = 32768 if request.url.path == '/api/v1/settings/provider' else 8 * 1024 * 1024
                    if len(body) > limit:
                        return error_response(request, DomainError('REQUEST_TOO_LARGE', status=413))
                try:
                    strict_loads(bytes(body))
                except (ValueError, TypeError, RecursionError):
                    return error_response(request, DomainError('REQUEST_INVALID', status=422))
                request._body = bytes(body)
        result = await call_next(request)
        result.headers['X-Request-ID'] = request.state.request_id
        result.headers['X-Content-Type-Options'] = 'nosniff'
        result.headers['Referrer-Policy'] = 'no-referrer'
        result.headers.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-src 'self'; base-uri 'none'; frame-ancestors 'self'")
        return result

    def error_response(request, exc):
        return JSONResponse({'error': {'code': exc.code, 'message': exc.message, 'retryable': exc.retryable,
            'resource_id': exc.resource_id, 'details': exc.details}, 'request_id': getattr(request.state, 'request_id', None)}, status_code=exc.status)

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic's default error includes submitted body values; do not echo them.
        return error_response(request, DomainError('REQUEST_INVALID', status=422, details={'fields': [list(e['loc']) for e in exc.errors()]}))

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logging.getLogger('library').error('request_failed request_id=%s type=%s', getattr(request.state, 'request_id', None), type(exc).__name__)
        return error_response(request, DomainError('INTERNAL_ERROR', status=500))

    @app.get('/health/live')
    def live():
        return {'status': 'ok'}

    @app.get('/health/ready')
    def ready():
        try:
            if app.state.db is None:
                raise DomainError('DATABASE_CONFIG', status=503)
            app.state.db.ready()
            from packages.parsers.models import parser_version
            if not parser_version():
                raise DomainError('PARSER_MANIFEST_MISSING', status=503)
            if not cfg.data.is_dir() or not cfg.uploads.is_dir():
                raise DomainError('VOLUME_UNAVAILABLE', status=503)
            from packages.maintenance.__main__ import verify_data
            from packages.templates import list_templates
            integrity = verify_data(app.state.db, cfg)
            list_templates()
            if not (web_root / 'index.html').is_file():
                raise DomainError('FRONTEND_UNAVAILABLE', status=503)
            with app.state.db.transaction() as session:
                for dependency in ('worker', 'parser'):
                    pulse = session.get(Heartbeat, dependency)
                    if not pulse or pulse.at < now() - timedelta(seconds=45):
                        raise DomainError('DEPENDENCY_UNAVAILABLE', status=503, details={'dependency': dependency})
            return {'status': 'ready', 'schema_version': SCHEMA_VERSION, 'verified_objects': integrity['objects']}
        except DomainError as exc:
            raise DomainError(exc.code, status=503, details=exc.details) from exc
        except Exception as exc:
            raise DomainError('DEPENDENCY_INTEGRITY_FAILURE', status=503) from exc

    @app.get('/api/v1/capabilities')
    def capabilities():
        from packages.parsers.profiles import PARSER_PROFILES
        profile = provider_profile()
        return {'phase': cfg.phase, 'source_mime_types': ['application/pdf'], 'provider_configured': bool(profile.get('configured')),
            'features': {'translation': cfg.phase != 'M0', 'editorial': cfg.phase == 'M2', 'ocr': cfg.phase != 'M0', 'accounts': False},
            'limits': {'pdf_bytes': cfg.max_pdf_bytes, 'pages': cfg.max_pages, 'batch': 10, 'chunk_bytes': cfg.chunk_bytes,
                'max_pdf_bytes': cfg.max_pdf_bytes, 'max_pages': cfg.max_pages, 'max_batch_files': 10,
                'text_codepoints': 1000000, 'blocks': 10000, 'parser_concurrency': 1, 'translation_concurrency': 2},
            'language_policy': 'all', 'parser_profiles': PARSER_PROFILES}

    app.include_router(library_router)
    # Missing domain modules are a deployment failure, never silently hidden.
    for module in ('workflow', 'editorial', 'artifacts', 'catalog', 'sources', 'candidates', 'knowledge', 'provider_settings', 'continuation'):
        imported = __import__('apps.api.' + module, fromlist=['router'])
        app.include_router(imported.router)

    web_root = Path(os.environ.get('WEB_DIST_DIR', str(Path(__file__).parents[1] / 'web' / 'dist')))

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'], include_in_schema=False)
    def frontend(path: str):
        if path.startswith(('api/', 'artifacts/', 'exports/', 'read/')):
            return JSONResponse({'error': {'code': 'NOT_FOUND'}}, status_code=404)
        if path:
            candidate = safe_path(web_root, path)
            if candidate.is_file():
                return FileResponse(candidate)
        index = web_root / 'index.html'
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({'status': 'frontend_build_required'}, status_code=503)
    return app


app = create_app()
