"""Generate fresh offline reader inputs for the independent content browser suites.

Run with the locked test image, current src/tests/res read-only, and no network.
The optional --math-input is a read-only historical reviewed-source directory:
response.json, remaining-math-reviewed-plans.json and data/ (original page PNGs
and source assets). Those prior review decisions are replay inputs, not a new
manual review, parser/model run, or API/database test. No old HTML is reused.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import zipfile

from packages.editorial.drafts import render_input, validate_target
from packages.ir import digest, validate_ir, validate_source
from packages.paths import ROOT
from packages.publisher import Publisher, export_bundle, export_single_html, verify_artifact
from packages.source_revisions import apply_native_corrections
from packages.source_revisions.math_crop import page_crop_factory
from packages.storage import file_hash
from packages.templates.registry import get_template

sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def hashes(root):
    return {path.relative_to(root).as_posix(): file_hash(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


def exports(ir, assets, folder):
    folder.mkdir(parents=True, exist_ok=False)
    validate_ir(ir, asset_root=assets)
    Publisher().build(ir, assets, folder / 'published', include_source=True)
    export_single_html(folder / 'published', folder / 'single.html', include_source=False)
    export_bundle(folder / 'published', folder / 'bundle.zip', include_source=False)
    with zipfile.ZipFile(folder / 'bundle.zip') as bundle:
        bundle.extractall(folder / 'bundle')
    verify_artifact(folder / 'published')
    verify_artifact(folder / 'bundle')
    write(folder / 'render-input.json', ir)


def complex_readers(root):
    fixture = read(ROOT / 'tests/fixtures/complex-reader/document-ir.json')
    folder = root / 'complex'
    folder.mkdir()
    for name in ('reader-v1', 'reader-v2'):
        ir = render_input(fixture['document']['id'], fixture['source_revision'], fixture['translation_revision'], name)
        exports(ir, ROOT / 'tests', folder / name)
        shutil.copyfile(folder / name / 'single.html', folder / (name + '.html'))
        shutil.copytree(folder / name / 'bundle', folder / (name + '-extracted'))


def hostile_reader(root):
    from tests.integration.test_hostile_reader import PAYLOAD, assert_safe_literal

    fixture = read(ROOT / 'tests/fixtures/sample-document.json')
    block = next(block for block in fixture['source_revision']['blocks'] if block['id'] == 'item')
    target = [{'type': 'text', 'text': PAYLOAD}]
    validate_target(target, fixture['source_revision'], block)
    result = next(result for result in fixture['translation_revision']['results'] if result['block_id'] == 'item')
    result.update(target_inline=target, status='translated')
    ir = render_input(fixture['document']['id'], fixture['source_revision'], fixture['translation_revision'], 'reader-v1')
    folder = root / 'hostile'
    exports(ir, ROOT / 'tests', folder)
    for file in (folder / 'single.html', folder / 'bundle/index.html'):
        assert_safe_literal(file.read_text(encoding='utf-8'))
    write(folder / 'verification.json', {'payload': PAYLOAD, 'scope': 'Current validate_target, Publisher and offline export; authored hostile literal. No API/database/model call.'})


def draft_ir(source, template):
    fixture = read(ROOT / 'tests/fixtures/sample-document.json')
    translation = copy.deepcopy(fixture['translation_revision'])
    example = translation['results'][1]
    translation.update(source_revision_id=source['id'], title='DRAFT', results=[{
        **copy.deepcopy(example), 'block_id': block['id'], 'source_hash': block['source_hash'],
        'status': 'unresolved', 'target_inline': [], 'review_state': 'not_reviewed', 'review_record': None,
    } for block in source['blocks']])
    translation['results'][0]['target_inline'] = [{'type': 'text', 'text': 'DRAFT'}]
    return render_input('doc_review_efficient', source, translation, template, mode='draft')


def math_readers(root, prior_dir):
    from PIL import Image

    prior = read(prior_dir / 'response.json')
    plan = read(prior_dir / 'remaining-math-reviewed-plans.json')
    original = prior['source']
    assert digest(original) == plan['source_hash']
    assert len(plan['candidates']) == 86
    input_hashes = hashes(prior_dir / 'data')
    manifest = {
        'input_directory': str(prior_dir), 'response_sha256': file_hash(prior_dir / 'response.json'),
        'review_plan_file': 'remaining-math-reviewed-plans.json',
        'review_plan_sha256': file_hash(prior_dir / 'remaining-math-reviewed-plans.json'),
        'historical_reviewer': plan['reviewer'], 'historical_review_status': plan['status'],
        'historical_review_scope': plan['scope'], 'source_hash': digest(original),
        'input_assets_sha256': input_hashes,
        'limitation': 'Replays 86 historical review decisions using current code. No new manual judgment, PDF parsing, model, database, API or publication-pointer operation.',
    }
    for scope in ('caption', 'all'):
        workspace = root / (scope + '-work')
        workspace.mkdir()
        assets = workspace / 'data'
        shutil.copytree(prior_dir / 'data', assets)
        source = copy.deepcopy(original)
        audit = []
        candidates = [item for item in plan['candidates'] if scope == 'all' or item['kind'] == 'caption']
        assert len(candidates) == (2 if scope == 'caption' else 86)
        for index, item in enumerate(candidates):
            block = next(block for block in source['blocks'] if block['id'] == item['block_id'])
            assert item['visual_review_confirmed'] is True
            assert block['normalized_text'][item['start']:item['end']] == item['math_substring']
            operation = {key: item[key] for key in ('block_id', 'start', 'end', 'page', 'bbox', 'page_image_sha256', 'visual_review_confirmed')}
            operation['kind'] = 'annotate_math_crop'
            draft = SimpleNamespace(id=f'replay-{scope}-{index}', evidence=prior['evidence'])
            changed = apply_native_corrections(source, prior['evidence']['inspection'], [operation],
                item['evidence'], item['review_reason'], [], crop_asset=page_crop_factory(assets, 'doc_review_efficient', draft))
            source = changed['source']
            restoration = changed['restorations'][0]
            asset = restoration['asset']
            page = next(page for page in prior['evidence']['inspection']['pages'] if page['page'] == item['page'])
            page_path = assets / prior['evidence']['page_images'][str(item['page'])]
            assert file_hash(page_path) == item['page_image_sha256']
            with Image.open(page_path) as image, Image.open(assets / asset['storage_key']) as crop:
                sx, sy = image.width / page['page_size'][0], image.height / page['page_size'][1]
                box = item['bbox']
                expected = image.crop((math.floor(box[0]*sx), math.floor(box[1]*sy), math.ceil(box[2]*sx), math.ceil(box[3]*sy)))
                assert crop.size == expected.size and crop.tobytes() == expected.tobytes()
            audit.append({'operation': operation, 'source_after': digest(source), 'restoration': restoration, 'exact_original_pixels': True})
            if (index + 1) % 10 == 0:
                print(f'{scope}: {index + 1}/{len(candidates)} current-code corrections', flush=True)
        assert all(file_hash(assets / key) == value for key, value in input_hashes.items())
        by_id = {block['id']: block for block in source['blocks']}
        assert all(by_id[block['id']]['raw_text'] == block['raw_text'] and by_id[block['id']]['owner_id'] == block['owner_id'] for block in original['blocks'])
        validate_source(source, asset_root=assets)
        response = {'source': source, 'source_hash': digest(source), 'evidence_scope': manifest['limitation']}
        targets = [(root / scope, 'reader-v1')]
        if scope == 'all':
            targets += [(root / 'anchor' / template, template) for template in ('reader-v1', 'reader-v2')]
        for folder, template in targets:
            exports(draft_ir(source, template), assets, folder)
            write(folder / 'response.json', response)
            write(folder / 'replayed-operations.json', audit)
        manifest[scope] = {'operations_replayed': len(audit), 'source_after': digest(source), 'all_crops_exact_original_pixels': True,
            'all_original_assets_raw_text_and_owners_unchanged': True}
    assert hashes(prior_dir / 'data') == input_hashes
    return manifest


def generate(output, prior_dir, revision, image_id):
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        'created_at': datetime.now(timezone.utc).isoformat(), 'source_revision': revision, 'locked_image_id': image_id,
        'generator_sha256': file_hash(Path(__file__)), 'network': 'disabled in generator container',
        'fixture_files': {str(path.relative_to(ROOT)): file_hash(path) for path in (
            ROOT / 'tests/fixtures/sample-document.json', ROOT / 'tests/fixtures/complex-reader/document-ir.json',
            ROOT / 'tests/fixtures/complex-reader/authored-source-manifest.json', ROOT / 'tests/integration/test_hostile_reader.py')},
        'runtime_source_sha256': {str(path.relative_to(ROOT)): file_hash(path)
            for directory in ('src/packages/publisher', 'src/packages/source_revisions', 'src/packages/templates')
            for path in sorted((ROOT / directory).rglob('*')) if path.is_file() and path.suffix in {'.py', '.js', '.css'}},
        'templates': [get_template(name) for name in ('reader-v1', 'reader-v2')],
        'scope': 'Fresh current-code local renderer/export evidence from authored fixtures and optional historical hash-bound review input; never a new parser/provider/API certification.',
    }
    complex_readers(output)
    hostile_reader(output)
    if prior_dir:
        manifest['math'] = math_readers(output, prior_dir)
    manifest['output_sha256'] = hashes(output)
    write(output / 'manifest.json', manifest)
    print(json.dumps({'output': str(output), 'status': 'generated', 'math': bool(prior_dir)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='New directory in the isolated temporary output mount')
    parser.add_argument('--math-input', type=Path, help='Read-only reviewed-source input directory described above')
    parser.add_argument('--source-revision', required=True, help='Inspected checkout commit; file hashes are recorded too')
    parser.add_argument('--image-id', required=True, help='Inspected locked Docker image digest')
    args = parser.parse_args()
    generate(args.output.resolve(), args.math_input.resolve() if args.math_input else None, args.source_revision, args.image_id)
