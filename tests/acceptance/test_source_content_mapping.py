"""Authored PDF/IR mapping fixtures, expressly not Docling source-gold evidence."""
import copy
import json
import os
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from packages.ir import block_hash, digest, validate_source
from packages.source_revisions import revision_mapping

ROOT = Path(__file__).resolve().parents[2]


def authored_source(folder, prefix, sentences, *, id_prefix=None, atom_kind='number'):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (prefix + '.pdf')
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    instructions = []
    for index, text in enumerate(sentences):
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        instructions.append(f'BT /F1 11 Tf 50 {740-index*30} Td ({escaped}) Tj ET')
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(instructions).encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    with path.open('wb') as handle:
        writer.write(handle)
    # These are actual new PDF bytes containing the declared inserted paragraph.
    extracted = PdfReader(path).pages[0].extract_text()
    positions = [extracted.find(sentence) for sentence in dict.fromkeys(sentences)]
    assert min(positions) >= 0 and positions == sorted(positions)

    source = json.loads((ROOT / 'fixtures/sample-document-v3.json').read_text())['source_revision']
    heading = copy.deepcopy(source['blocks'][0])
    paragraph = copy.deepcopy(next(b for b in source['blocks'] if b['id'] == 'p2'))
    prefix_id = id_prefix or prefix
    asset = 'pdf-' + prefix
    source.update(id='source-' + prefix, original_asset_id=asset, sha256=digest(path.read_bytes()),
        title_block_id=prefix_id + '-0', protected_atoms={}, blocks=[], reading_order=[])
    source['assets'] = [{'id': asset, 'media_type': 'application/pdf', 'sha256': source['sha256'],
        'storage_key': path.name, 'byte_size': path.stat().st_size}]
    for index, sentence in enumerate(sentences):
        block = copy.deepcopy(heading if index == 0 else paragraph)
        block.update(id=f'{prefix_id}-{index}', order=index, parent_id=None if index == 0 else source['title_block_id'],
            raw_text=sentence, normalized_text=sentence, normalization_edits=[], source_inline=[{'type': 'text', 'text': sentence}])
        if '64' in sentence:
            left, right = sentence.split('64')
            ref = prefix + '-number-' + str(index)
            source['protected_atoms'][ref] = {'kind': atom_kind, 'value': '64'}
            block['source_inline'] = [{'type': 'text', 'text': left}, {'type': 'protected_ref', 'ref': ref}, {'type': 'text', 'text': right}]
        block['provenance'] = [{'type': 'pdf', 'asset_id': asset, 'page': 1,
            'bbox': [50, 40+index*30, 400, 55+index*30], 'coordinate_system': 'top-left-points', 'page_size': [612, 792]}]
        block['source_hash'] = block_hash(block, source['protected_atoms'])
        source['blocks'].append(block)
        source['reading_order'].append(block['id'])
    validate_source(source, asset_root=folder)
    (folder / (prefix + '.source.json')).write_text(json.dumps(source, indent=2))
    return source


def output_folder(tmp_path, case):
    return Path(os.environ.get('MAPPING_EVIDENCE_DIR', str(tmp_path))) / case


def test_new_pdf_prepend_matches_content_and_resolved_atoms_despite_all_ids_changing(tmp_path):
    folder = output_folder(tmp_path, 'shifted-identifiers')
    sentences = ['Mapping fixture', 'Context alpha.', 'Cache holds 64 tokens.', 'The result remains stable.', 'Context omega.']
    before = authored_source(folder, 'old', sentences)
    after = authored_source(folder, 'new', [sentences[0], 'Inserted paragraph.', *sentences[1:]])
    assert before['sha256'] != after['sha256']
    assert not set(b['id'] for b in before['blocks']).intersection(b['id'] for b in after['blocks'])
    old_hash, new_hash = digest(before), digest(after)
    mapping = revision_mapping(before, after)
    (folder / 'observed-mapping.json').write_text(json.dumps(mapping, indent=2))
    by_old = {tuple(row['old_block_ids']): row for row in mapping if len(row['old_block_ids']) == 1}
    for old_index in range(1, len(sentences)):
        row = by_old[(f'old-{old_index}',)]
        assert row['new_block_ids'] == [f'new-{old_index+1}'], row
        # The paragraph next to the insertion has changed context; the others
        # retain the same resolved text/atom/section/neighbour meaning.
        assert row['reusable'] is (old_index >= 2), row
    assert digest(before) == old_hash and digest(after) == new_hash


def test_equal_text_under_changed_section_is_never_reusable(tmp_path):
    folder = output_folder(tmp_path, 'changed-context')
    before = authored_source(folder, 'old', ['Memory results', 'Cache holds 64 tokens.', 'Context omega.'], id_prefix='stable')
    after = authored_source(folder, 'new', ['Energy results', 'Cache holds 64 tokens.', 'Context omega.'], id_prefix='stable')
    row = next(r for r in revision_mapping(before, after) if r['old_block_ids'] == ['stable-1'])
    assert row['reusable'] is False and row['context_changed'] is True


def test_equal_visible_text_with_changed_protected_atom_semantics_is_never_reusable(tmp_path):
    folder = output_folder(tmp_path, 'changed-atoms')
    sentences = ['Mapping fixture', 'Cache holds 64 tokens.', 'Context omega.']
    before = authored_source(folder, 'old', sentences, id_prefix='stable', atom_kind='number')
    after = authored_source(folder, 'new', sentences, id_prefix='stable', atom_kind='math')
    assert before['blocks'][1]['normalized_text'] == after['blocks'][1]['normalized_text']
    row = next(r for r in revision_mapping(before, after) if r['old_block_ids'] == ['stable-1'])
    assert row['reusable'] is False


def test_repeated_identical_context_cannot_reuse_by_coincidental_ordinal_id(tmp_path):
    folder = output_folder(tmp_path, 'ambiguous-repeated-content')
    sentences = ['Mapping fixture', 'Lead context.', *(['Repeated claim.'] * 5), 'End context.']
    before = authored_source(folder, 'old', sentences, id_prefix='ordinal')
    after = authored_source(folder, 'new', [sentences[0], 'Inserted paragraph.', *sentences[1:]], id_prefix='ordinal')
    mapping = revision_mapping(before, after)
    (folder / 'observed-mapping.json').write_text(json.dumps(mapping, indent=2))
    # Interior repeated claims have indistinguishable immediate context. The
    # shared ordinal ID is not provenance that identifies an unchanged block.
    for old_id in ('ordinal-3', 'ordinal-4', 'ordinal-5'):
        row = next(r for r in mapping if r['old_block_ids'] == [old_id])
        assert row['reusable'] is False, row
