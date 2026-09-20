# Current workflows

## From PDF to publication

Upload inspection verifies the PDF before library import. Parsing freezes the
selected profile, accelerator and timeout. Newly saved preferences use
PaddleOCR-VL-1.6; older explicit preferences and queued jobs are preserved.

Source extraction is followed by page coverage checks and bounded recovery using
the original PDF. Missing regions that cannot be safely recovered remain visible
as source text or page images. Recovery tasks expose before/after comparisons.
Source-only results provide an explicit continuation action; translation uses the
saved source rather than implying parsing already produced a translation.

Native page/column edges can join a continuing sentence across a floating figure
or footnote when the original glyphs support both ends. Complete sentences and
intervening headings remain separate. Same-baseline equation numbers and nearby
subfigure labels stay with their equations/figures. These repairs retain the PDF
locators and before/after audit; they affect new source revisions only.
Native margin evidence excludes folios and arXiv stamps. Sequential numbered
items with hanging indents form lists, and native table rows distinguish actual
line breaks from literal code escapes. A narrowly matched native paragraph can
also correct one misrecognized word; conflicting evidence stays visible.
Native evidence also repairs unambiguous same-column ordering and split
references. Reference numbers and author characters are corrected only when
complete native lines and the unchanged citation body identify the same entry.
An unknown native glyph can be reconciled only when its embedded font encoding
and an independent extraction agree at the same position; genuine question marks
and ambiguous mappings stay unchanged.

Translation requires a complete saved profile, content/destination confirmation,
enabled dispatch and a budget when cost control is enabled. Confirmations bind the
source, profile revision/hash and current generation. Changing them requires a new
confirmation. Waiting for model/configuration startup is represented separately
from an unknown provider outcome.

Content checks produce hints and comparison evidence. They do not require manual
approval to seal, publish or export. Invalid executable content is rejected or
safely represented before rendering; nonblocking quality does not relax file,
version or secret boundaries. Successfully sealed revisions are immutable.

## Original-only academic content

[ir/retention.py](../src/packages/ir/retention.py) recognizes supported author bylines,
affiliations, contact lines, DOI/ORCID identifiers and bibliography ranges. It uses
structure and positive metadata evidence; ambiguous prose remains translatable.
Bibliography retention stops at the next prose section.

Detected blocks create no translation units and are excluded from request context.
They are retained once, with their original links and formatting, in bilingual,
source-only and target-only readers and exports. The detector does not rewrite
source text or retroactively change existing sealed translations/publications.
Retained content is neither a translation failure nor a human-review claim.

Numeric and math-only table cells, model identifiers and isolated identifier
subcaptions are retained once. Known full names from confirmed author/affiliation
metadata stay literal inside translated prose. Complete numeric and author-year
citations, including their original brackets/separators, and delimited inline TeX
are protected before translation. Short unambiguous numeric citations remain
visible to local translation models; equivalent output typography restores their
exact source spelling, while missing or changed numbers remain quality findings.
Distinctive system identifiers explicitly named before a title colon remain
literal in table cells, while surrounding header prose stays translatable.
Local translation requests contain only their
source unit and translation instructions, so neighbouring paragraphs cannot be
translated in place of the requested text. Explicit numeric scales
use exact target formatting for Chinese (for example, `8.3 billion` becomes
`83亿`); source text and quantity values remain unchanged. Abbreviated `M`/`B`
scales require parameter/model context, so byte units and identifiers are not
treated as model sizes. Numeric equivalence never exempts missing citations or
formulas from quality checks.

Reader blocks use tighter padding and gaps, smaller corners, softer borders and backgrounds,
and no card shadows. Body font sizes and line spacing remain unchanged.

New publications and draft exports use `reader-v9`: a font selector beside the size buttons offers
default, serif, sans-serif, monospace, 方正宋体, 方正黑体, 思源宋体, 思源黑体,
MiSans, 鸿蒙黑体 and Noto Sans Simplified Chinese. The choice is saved in browser
storage. Named fonts use installed local copies, with local fallbacks when missing;
the selector tooltip explains this, and exports work offline without downloading fonts.
The Noto choice uses the [Noto Sans SC family](https://github.com/google/fonts/blob/main/ofl/notosanssc/METADATA.pb).
The TOC uses the original section labels,
author/affiliation lines share the title area, and adjacent list items share a
list. Footnotes with an explicit source cross-reference appear beside each citing
block, including repeated citations. Clear superscript or symbol markers also
link to a uniquely labelled footnote on the same page; unlinked notes remain in the reading flow.
Inline numeric and author–year citations open the matching original bibliography
entries in that block's margin. Matching uses only unique labels or author/year
evidence in the saved document; unresolved or ambiguous citations stay readable
without a guessed link. Reference cards close with their button or Escape and
return focus to the citation. Without JavaScript, citation links lead to the
bibliography. At widths of 1200px and above, notes, references, content hints and
original-page comparisons occupy the side column; compact screens place them
below the citing block. Footnotes remain visible when printing. Figures fill the column within the
viewport height, tables stack source and target text in compact cells with one
original-table comparison, and contiguous reference entries share one bibliography
block while retaining their individual anchors. Inline and display TeX use bundled
KaTeX with native MathML output, bounded expansion and untrusted-input settings;
invalid formulas retain readable text and PDF comparison. Both ZIP and single-HTML
exports include the math runtime and work offline. Older templates/artifacts remain
available unchanged.

## Editing, languages and history

Segment edits, selected translation candidates, source corrections and optional
semantic review retain version checks and provenance. Manual review is optional
and becomes stale when its bound text changes. Semantic review produces findings,
not replacement translations; local translation-only models do not provide it.

All valid supported language tags may be selected, including custom tags. Names
are shown in their own language where available. Locale normalization preserves
script/region differences such as `zh-Hans`, `zh-Hant`, `pt` and `pt-BR`.
Language availability does not certify a model's translation quality.

The task center lists parent tasks, with paginated child tasks and logs in details.
Clearing finished history applies across pages and filters, while retaining the
documents, task records, logs, attempts and costs. Active/waiting tasks and those
with active or unknown permits are ineligible. Changed jobs become visible again;
“显示已清除历史” includes hidden records. Clearing requires generation and idempotency
checks and is not data deletion.

## Provider settings and uncertain requests

Saving endpoint, protocol, model and optional key does not test them. An empty key
preserves the current secret; clearing is explicit. Destination/protocol/auth changes
cannot silently reuse an old key. Native response identities must match the selected
model; Gemini permits only the supported `models/` prefix equivalence. No protocol,
model or provider is silently substituted.

The external-request switch is durable database state. It gates translation,
semantic review and connection tests, independently of saved credentials and
per-operation confirmation. It does not disable DOI metadata lookup or explicit
local model downloads. Disabling it stops new permits; in-flight requests still
settle. Restoring a backup does not enable it.

New profiles default to cost control off. Known usage may still be recorded and
unknown amounts remain `null`. Enabled cost control uses reserved, actual and
unresolved-risk amounts without double counting. A timeout after dispatch remains
`outcome_unknown`; explicit risk acceptance is needed before retrying. An unknown
result is never treated as an unsent request or free work.
