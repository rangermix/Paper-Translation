"""Run genuine model conversion, or explicitly replay its frozen model output."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
from collections import Counter
import json
from pathlib import Path
import time

from packages.parsers.inspect import inspect_pdf
from packages.parsers.pdf_docling import DoclingParser


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pdf', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--replay')
    args = parser.parse_args()
    start = time.monotonic()
    adapter = DoclingParser()
    if args.replay:
        from docling_core.types.doc import DoclingDocument
        raw = json.loads(Path(args.replay).read_text())
        document = DoclingDocument.model_validate(raw)
        items = [item.model_dump(mode='json') for item, _ in document.iterate_items()]
        seen = {item.get('self_ref') for item in items}
        items.extend(item for item in raw.get('texts', []) if item.get('label') in {'page_header', 'page_footer'} and item.get('self_ref') not in seen)
        result = adapter.adapt(items, inspect_pdf(args.pdf), args.pdf, 'original-pdf', args.output)
        execution = 'adapter_replay_of_recorded_real_model_output'
    else:
        result = adapter.parse(args.pdf, 'original-pdf', args.output)
        execution = 'real_docling_layout_and_table_model_inference'
    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    coverage = result['coverage']
    summary = {'execution': execution, 'seconds': round(time.monotonic()-start, 3),
        'pages': result['inspection']['page_count'],
        'blocks': len((result.get('source_revision') or {}).get('blocks', [])),
        'can_translate': coverage['can_translate'],
        'issues': len(coverage['unresolved']),
        'issue_reasons': dict(Counter(issue.get('reason', issue['code']) for issue in coverage['unresolved']))}
    (destination / 'execution.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
