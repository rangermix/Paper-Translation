# Original-only academic content

Implemented on 2026-09-16. This policy supplements the nonblocking workflow and overrides the older requirement to translate every prose-shaped block for the categories below.

New translation planning detects and retains:

- Author bylines supported by an author label, affiliation markers, or adjacent affiliation/contact evidence in the contiguous front matter after the title.
- Institution and organisation affiliations in that front matter.
- Short lines consisting only of email contacts, URLs, DOI or ORCID identifiers.
- Parser-labelled references, recognised bibliography/reference headings, and their paragraph, list, footnote and table-cell entries up to the next section.

Reference heading matching accepts numbered headings and common English, Chinese, Japanese, Korean and European-language labels. It also recognises paragraph-style headings when the parser has not marked them as headings. Appendix, author-contribution, acknowledgment, funding and other recognised prose-section labels end a reference range.

Detection is deliberately conservative. Ambiguous name-shaped or title-cased text without metadata evidence remains translatable. A title, abstract, ordinary body/list/caption, substantive footnote, or acknowledgment does not become original-only merely because it mentions authors, organisations or references. A block containing both metadata and substantive prose remains eligible for translation. This is deterministic pattern recognition, not a guarantee for every PDF layout or language.

## Translation and editing

`packages/ir/retention.py` owns the read-only `academic-original-only-v1` policy. It uses source structure, reading order and extracted text; it does not call a model, fetch metadata, change source text/AST/hash/provenance, or mutate the source `translatable` field. The same policy is used for unit planning, preflight counts, draft editability, candidate/review selections, glossary impact, QA and sealed-result validation. Detected content is also omitted from adjacent request context.

New sealed results use `status=retained`, an empty `target_inline`, and one of `original_author_list`, `original_affiliation`, `original_contact`, `original_identifier`, `original_bibliography_heading` or `original_reference`. These are intentional skips, not missing translations or fallback failures. They do not create translation tasks, translation permits, missing-translation findings or human-review claims. Existing code, formula and image retention continues.

The source validator still rejects arbitrary `translatable=false` on required prose. The result validator only permits a new retention reason when it matches the detected block. Old segment and review records are retained, but no obsolete target/review is attached to a newly retained original.

## Static reading and compatibility

Reader renderer `reader-python-3.2.0` displays retained text once at full available width, without an empty translation column or a missing-translation message. Retained paragraphs and headings remain visible in bilingual, source-only and target-only views, in both export formats, and without JavaScript. Original inline links and formatting use the existing escaped source renderer.

This applies when creating new translations from newly parsed or already saved source revisions. It does not reparse existing PDFs, rewrite source snapshots, retroactively remove translations from sealed revisions, regenerate published pages, or trigger model requests. Existing artifacts remain immutable. New builds read the retained/translated status recorded in their sealed translation. No database migration, model download or template CSS/JavaScript change is required; frozen reader-v1 CSS is unchanged.

## Verification and deployment scope

The implementation checkpoint is `27d6848`. Targeted verification passed 188 Python tests, including a dedicated Compose PostgreSQL instance with the production queue, QA, sealing and publishing paths. FakeProvider call records prove detected content produces no translation units; this does not claim live-provider or translation-quality certification.

Three Chromium browser checks passed using the repository Playwright runner: offline single HTML and the artifact file set at 1440×1060 and 390×844, language toggles, reference navigation, no horizontal overflow, no network requests/errors, and JavaScript-disabled readability. The Browser plugin was not available. Source/history preservation and a separate code review were included. Two existing dependency deprecation warnings from Starlette/AnyIO were observed.

Commands, red/green test logs, synthetic static artifacts and screenshots are in `.agent/tmp/original-only-20260916-a6610dd9/`. No user credentials or real translation model were used. The running production containers were not redeployed. Deploy the updated app and worker through the existing Compose procedure to enable this for future translations; existing published pages require a new translation revision to adopt newly detected retention.
