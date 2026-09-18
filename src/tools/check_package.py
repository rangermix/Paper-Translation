#!/usr/bin/env python3
"""Check maintained repository inputs; never call providers or certify a deployment."""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote
from uuid import uuid4

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from packages.ir import digest, validate_ir
from packages.templates import list_templates


def package_files(suffix=None):
    """Skip local configuration, credentials, dependencies and archived agent runs."""
    excluded = {'.git', '.agent', '.local-data', '.vscode', '.venv', 'venv',
                'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache',
                '.ruff_cache', 'dist', 'test-results', 'playwright-report',
                'secrets', 'provider_config'}
    for directory, dirs, names in os.walk(ROOT, followlinks=False):
        dirs[:] = [name for name in dirs if name not in excluded
                   and not (Path(directory) / name).is_symlink()]
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or name == '.env' or (name.startswith('.env.') and name != '.env.example'):
                continue
            if path.parent == ROOT and name == 'compose.yaml':
                continue
            if path.parent == ROOT / 'deployment' and name.startswith('provider_key.'):
                continue
            if suffix is None or path.suffix == suffix:
                yield path


def load(path):
    return json.loads((ROOT / path).read_text('utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_fixture():
    sample = load('tests/fixtures/sample-document.json')
    validate_ir(sample, asset_root=ROOT / 'tests')
    kinds = load('res/schemas/document-ir.schema.json')['$defs']['block']['properties']['kind']['enum']
    require({block['kind'] for block in sample['source_revision']['blocks']} == set(kinds), 'Missing fixture block kind')
    validate_ir(load('tests/fixtures/complex-reader/document-ir.json'), asset_root=ROOT / 'tests')


def check_resources():
    for relative, expected in load('res/reference/reference-files.sha256.json').items():
        require(digest((ROOT / 'res' / relative).read_bytes()) == expected, 'Changed reference: ' + relative)
    list_templates()  # Checks the actual runtime template hashes and resource paths.


def check_compose():
    production = yaml.safe_load((ROOT / 'compose.example.yaml').read_text())
    services = production['services']
    core = {name: service for name, service in services.items() if not service.get('profiles')}
    require(set(core) == {'init', 'db', 'migrate', 'app', 'worker', 'parser'}, 'Unexpected default services')
    require([name for name, service in core.items() if 'ports' in service] == ['app'], 'Unexpected product port')
    require('127.0.0.1' in services['app']['ports'][0], 'Default bind is not loopback')
    require(services['parser']['network_mode'] == 'none' and not services['parser'].get('secrets'), 'Default parser isolation')
    require(not production.get('secrets') and not any(s.get('secrets') for s in services.values()), 'Unexpected external secret mount')
    require(not any({'PROVIDER_PROFILE_FILE', 'PROVIDER_KEY_FILE'} & s.get('environment', {}).keys()
                    for s in services.values()), 'Provider settings must come from the application')
    for name in ('init', 'app', 'worker'):
        require('provider_config:/provider_config' + (':ro' if name == 'worker' else '') in services[name]['volumes'],
                'Managed provider configuration access: ' + name)
    require('docker.sock' not in str(services), 'Docker socket in product services')
    require(set(services['tests']['depends_on']) == {'test-db'} and services['test-db']['profiles'] == ['tests'],
            'Tests must use only the isolated test database')
    require(not services['test-db'].get('volumes') and services['test-db']['networks'] == ['test_backend'],
            'Test database must not share product storage or networks')
    require(not production['networks']['test_backend'].get('internal', False),
            'Test database bridge must publish its loopback port for host tests')
    checks = services['checks']
    require(checks['network_mode'] == 'none' and checks['read_only'], 'Repository check isolation')
    require(not any(checks.get(key) for key in ('ports', 'volumes', 'secrets', 'depends_on')), 'Repository checks access services or volumes')


def check_markdown():
    for path in package_files('.md'):
        for href in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)', path.read_text()):
            if href.startswith(('http:', 'https:', 'mailto:', '#')):
                continue
            target = (path.parent / unquote(href.split('#')[0])).resolve()
            # Agent records are optional in source exports and absent from images.
            if target.is_relative_to(ROOT / '.agent'):
                continue
            require(target.exists(), f'{path.relative_to(ROOT)} -> {href}')


class ResourceLinks(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = set()
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        field = 'href' if tag in {'a', 'link'} else 'src' if tag in {'img', 'script', 'iframe'} else None
        if field in attrs:
            self.links.append(attrs[field])


def check_seed_links():
    manifest = load('res/reference/legacy-manifest.json')
    patch = manifest['navigation_patch']
    pages = {}
    for item in manifest['documents']:
        path = (ROOT / 'res' / item['html_path']).resolve()
        pages[path] = ResourceLinks(path.read_text().replace(patch['from'], patch['to'], 1))
    for path, page in pages.items():
        for href in page.links:
            if href == '/' or href.startswith(('http:', 'https:', 'mailto:', 'data:', 'blob:', 'javascript:')):
                continue
            relative, _, anchor = href.partition('#')
            target = (path.parent / unquote(relative)).resolve() if relative else path
            require(target.exists(), f'{path.relative_to(ROOT)} -> {href}')
            if anchor and not anchor.startswith('/') and target in pages:
                require(unquote(anchor) in pages[target].ids, f'Unknown anchor: {path.name} -> {href}')


def main():
    checks = []
    actions = [
        ('Runtime IR schema syntax', lambda: jsonschema.Draft202012Validator.check_schema(load('res/schemas/document-ir.schema.json'))),
        ('Authored fixture syntax, semantics and asset bytes', check_fixture),
        ('Frozen seed resources and registered reader templates', check_resources),
        ('Product and test Compose boundaries (static only)', check_compose),
        ('Current Markdown links', check_markdown),
        ('Controlled seed HTML resources and anchors', check_seed_links),
    ]
    for name, action in actions:
        try:
            action()
            result = {'name': name, 'result': 'pass'}
        except Exception as error:
            result = {'name': name, 'result': 'fail', 'detail': str(error)}
        checks.append(result)
        print(result['result'].upper(), name, result.get('detail', ''))
    report = {'purpose': 'Repository input checks only; not runtime or model acceptance',
              'checks': checks, 'passed': sum(item['result'] == 'pass' for item in checks),
              'failed': sum(item['result'] == 'fail' for item in checks)}
    try:
        run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
        output = ROOT / '.agent/tmp/validation/runs' / run / 'package-validation.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    except OSError:
        pass  # The isolated check container is read-only; stdout remains the result.
    print(f"TOTAL {report['passed']} passed, {report['failed']} failed")
    return int(report['failed'] > 0)


if __name__ == '__main__':
    raise SystemExit(main())
