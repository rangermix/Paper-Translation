# Product scope

Paper Translation is a personal PDF library served by one Docker Compose instance.
FastAPI provides the API, files and React frontend directly. There is no account,
login, workspace or role system. Any client able to reach the service can operate
the instance; the default published address is loopback.

## Implemented workflow

- Upload, inspect and store PDFs; browse, search, tag, star and archive documents.
  Defaults are 50 MiB per PDF, 200 pages and ten files per upload batch.
- Parse full pages with Surya OCR 2 (the default for new preferences), Chandra
  OCR 2 or Infinity-Parser2 Pro/Flash through Docker Model Runner only. Settings
  controls the model and timeout. Queued jobs keep their recorded model/backend;
  retired/native choices fail explicitly rather than being reassigned. Docling
  and Granite inference are removed; Paddle, Xiaomi and TeleOCR are archived.
- Recover extraction gaps using original-PDF evidence, show unresolved content
  beside page images, and expose saved parse results for later translation.
  New source format 4.0 retains nested blocks/lists, rich table cells and headers,
  math/code, script and text formatting, safe links, printed captions and notes,
  plus verifiable per-page response evidence. Nested content inherits the real
  enclosing rectangle when the model supplies no finer coordinates. Generated
  figure/chemical descriptions stay labeled auxiliary evidence.
- Translate through a saved API service or the optional local translation service
  with platform-supported GGUF, Safetensors/vLLM, or Apple Silicon MLX models.
  All languages are selectable; model quality for each language is not guaranteed
  by the selector. Provider configuration and content processing require confirmation.
  Each translation task freezes its public service settings and credential revision
  when created. Later settings changes apply to new tasks; queued units and model
  preparation continue with the original revision.
  An opt-in upload default remembers permission for the current saved service, so
  later uploads can proceed from parsing to translation without checking consent
  again. Each upload can still opt out; changed service configurations require
  renewed permission and enabled cost controls still require a document budget.
- Prepare a source-grounded paper context and scoped terminology before translation.
  New requests default to deterministic extraction with no extra model call. Optional
  API analysis or a separate pinned MiniCPM5-1B local analyst adds a bounded analysis
  request. Settings selects the independent local analyst and inference backend,
  including GGUF/llama.cpp or MLX where supported by the deployment. New tasks freeze
  this selection; changing it does not replace an existing task's analyst.
  Inspect the draft, segment or candidate preparation and its source evidence;
  generated wording remains an unreviewed suggestion.
- Edit translations, request selected candidates, maintain terminology and explicit
  translation memories, correct source extraction, and optionally review segments
  or run model-assisted semantic checks.
- Seal immutable revisions, publish static bilingual readers, switch historical
  publications, and export self-contained HTML or a resource bundle. Draft exports
  clearly preserve missing translations as original content.
  New 4.0 sources use `reader-v11`; old source contracts and readers remain valid.
- Keep task stages, actual model identities, timings, redacted logs, attempts and
  uncertain outcomes. Clearing finished task history changes list visibility only.
  The [task model](task-model.md) defines which operations appear as main tasks
  and how they relate to internal steps and subsequent operations.
- Query Crossref asynchronously during upload for paper titles, authors and
  publication details, using a DOI or a conservatively matched title/author query.
  Retain the filename when lookup fails and preserve user-edited titles.
  Back up, restore, verify and clean storage through the maintenance service.

## Content and execution

Content issues are nonblocking. Automatic checks and deterministic recovery remain
active; damaged or unavailable content is represented safely as original text or
page imagery. Optional human review is never fabricated. Recognized author lists,
affiliations, contact/identifier lines and bibliographies remain original-only.

Execution failures, stale versions, unsafe paths, invalid resource hashes and
missing outbound authorization are separate from content warnings. A source-only
publication is not a translation. An uncertain paid request is not retried as
though nothing was sent. See [workflows](workflows.md).

## Configuration

The settings page supports Responses, Chat Completions, Gemini Interactions and
Claude Messages. Endpoints and model IDs are user-configurable; saving does not
send a request. Keys live in backend files and are never returned. Protocol,
authentication and native response model identity must agree with the saved profile.
Saved credential revisions remain available to tasks that already use them. There
is no automatic provider fallback.

Cost control defaults off for new settings and preserves existing choices.
Enabled control requires pricing and a positive job budget. Unknown amounts are
`null`, not zero. Input/output token limits default to 32768/8192 and unit text to
2000 characters; these are application limits, not model capability claims.

The shared source is packaged for Compose. Images contain no parser weights.
Parser, optional local translation and analyst weights are fetched only on explicit
preparation/use, pinned by revision, byte count and SHA-256. Parser startup and
settings reads/saves do not download models. A persistent parser cache is writable
only by its preparation service and read-only in the parser. All four active parsers use the same portable application client image, without
native inference frameworks. Docker's vLLM/vLLM Metal engine provides inference;
the selected model architecture and image-input path need backend support.
Model inference, arbitrary scanned-PDF accuracy and hardware support require
verification in the selected environment. Test fixtures and prior runs do not
certify all documents or an untested deployment.
