"""Repository paths for executable agent tooling and immutable legacy evidence.

Only known repository-relative prefixes are relocated. Historical records keep
their original strings and hashes; host-absolute paths are never replayed.
"""
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys


def repository_root():
    def has_source(candidate):
        # Historical schema-upgrade images retain the pre-src package layout.
        return (candidate / 'pyproject.toml').is_file() and any(
            (candidate / directory).is_dir() for directory in ('src/packages', 'packages'))

    for candidate in Path(__file__).resolve().parents:
        if has_source(candidate):
            return candidate
    # Reviewed helpers are also mounted at /harness in product test containers.
    candidate = Path('/app')
    if has_source(candidate):
        return candidate.resolve()
    raise RuntimeError('Cannot locate the product repository or container /app')


ROOT = repository_root()
AGENT = ROOT / '.agent'
TMP = AGENT / 'tmp'
for directory in (ROOT / 'src', ROOT, AGENT, Path(__file__).resolve().parent.parent, Path(__file__).resolve().parent):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


LEGACY_PREFIXES = (
    ('harness/memory', '.agent/memory'),
    ('apps/web/evidence', '.agent/tmp/frontend/evidence'),
    ('src/apps/web/evidence', '.agent/tmp/frontend/evidence'),
    ('harness', '.agent/harness'),
    ('notes', '.agent/notes'),
    ('evidence', '.agent/tmp/evidence'),
    ('reports', '.agent/tmp/reports'),
    ('.local-data', '.agent/local-data'),
    ('apps', 'src/apps'),
    ('packages', 'src/packages'),
    ('workers', 'src/workers'),
    ('tools', 'src/tools'),
    ('reference', 'res/reference'),
    ('fixtures', 'tests/fixtures'),
    ('ops', 'docs/ops'),
    ('images', 'deployment/images'),
)
LEGACY_FILES = {
    'apps/web/WORK_LOG.md': '.agent/notes/frontend-work-log.md',
    'reference/README.md': 'res/README.md',
    '00-product-baseline.md': 'docs/product-baseline.md',
    'deployment/extraction-acceleration.md': 'docs/deployment/extraction-acceleration.md',
    'deployment/local-translation.md': 'docs/deployment/local-translation.md',
    'deployment/mlx-backend/README.md': 'docs/deployment/mlx-backend.md',
    'deployment/Dockerfile.test': 'tests/Dockerfile',
    'deployment/images/test.Dockerfile': 'tests/Dockerfile',
    'deployment/production.env.example': '.env.example',
    'contracts/document-ir-v3.schema.json': 'res/schemas/document-ir.schema.json',
    'res/schemas/document-ir-v3.schema.json': 'res/schemas/document-ir.schema.json',
    'fixtures/sample-document-v3.json': 'tests/fixtures/sample-document.json',
    'fixtures/sample-document.json': 'tests/fixtures/sample-document.json',
    'ops/download_parser_models.py': 'src/tools/download_parser_models.py',
    'ops/export_parser_model.py': 'src/tools/export_parser_model.py',
    'src/apps/web/WORK_LOG.md': '.agent/notes/frontend-work-log.md',
    'package-review.md': '.agent/notes/package-review.md',
    'html/package-review.html': '.agent/tmp/validation/package-review.html',
    **{name: '.agent/tmp/validation/' + name for name in (
        'package-manifest.json', 'package-validation.json',
        'prototype-validation.json', 'server-validation.json')},
}


def artifact_path(path, root=ROOT):
    """Resolve a safe relative artifact path, including documented old prefixes."""
    value = str(path)
    windows = PureWindowsPath(value)
    if (not value or '\x00' in value or windows.drive or windows.root
            or PurePosixPath(value).is_absolute() or '://' in value):
        raise ValueError('Artifact path must be repository-relative')
    value = value.replace('\\', '/')
    if any(part == '..' for part in value.split('/')):
        raise ValueError('Artifact path cannot traverse a parent')
    value = PurePosixPath(value).as_posix()
    previous_project_prefix = 'bilingual-library-personal-pdf-v3/'
    if value.startswith(previous_project_prefix):
        value = value[len(previous_project_prefix):]
    if value in LEGACY_FILES:
        value = LEGACY_FILES[value]
    else:
        for old, new in LEGACY_PREFIXES:
            if value == old or value.startswith(old + '/'):
                value = new + value[len(old):]
                break
    root = Path(root).resolve()
    candidate = root
    for component in PurePosixPath(value).parts:
        candidate = candidate / component
        if candidate.is_symlink() or getattr(candidate, 'is_junction', lambda: False)():
            raise ValueError('Artifact path cannot contain a link')
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('Artifact path escapes repository')
    return resolved


def output_path(path, root=ROOT):
    """New review output must remain temporary; authorization receipts are not."""
    resolved = artifact_path(path, root)
    if not resolved.is_relative_to(Path(root).resolve() / '.agent/tmp'):
        raise ValueError('New review output must be inside .agent/tmp')
    return resolved
