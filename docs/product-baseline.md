# Product scope

Paper Translation is a personal PDF library served by one Docker Compose instance.
FastAPI provides the API, files and React frontend directly. There is no account,
login, workspace or role system. Any client able to reach the service can operate
the instance; the default published address is loopback.

## Implemented workflow

- Upload, inspect and store PDFs; browse, search, tag, star and archive documents.
  Defaults are 50 MiB per PDF, 200 pages and ten files per upload batch.
- Parse with PaddleOCR-VL-1.6 (the default for new preferences), Docling or Granite.
  The active CPU/CUDA/MLX mode in Compose determines the device. Settings controls
  the model and parsing timeout; queued jobs keep their recorded model, device and timeout.
- Recover extraction gaps using original-PDF evidence, show unresolved content
  beside page images, and expose saved parse results for later translation.
- Translate through a saved API service or the optional local MLX service.
  All languages are selectable; model quality for each language is not guaranteed
  by the selector. Provider configuration and content processing require confirmation.
- Edit translations, request selected candidates, maintain terminology and explicit
  translation memories, correct source extraction, and optionally review segments
  or run model-assisted semantic checks.
- Seal immutable revisions, publish static bilingual readers, switch historical
  publications, and export self-contained HTML or a resource bundle. Draft exports
  clearly preserve missing translations as original content.
- Keep task stages, actual model identities, timings, redacted logs, attempts and
  uncertain outcomes. Clearing finished task history changes list visibility only.
- Discover DOI metadata asynchronously, retaining the filename when lookup fails.
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
There is no automatic provider fallback.

Cost control defaults off for new settings and preserves existing choices.
Enabled control requires pricing and a positive job budget. Unknown amounts are
`null`, not zero. Input/output token limits default to 32768/8192 and unit text to
2000 characters; these are application limits, not model capability claims.

The shared source is packaged for Compose. Parser models are built into images;
optional local translation weights are fetched only on explicit preparation/use.
Model inference, arbitrary scanned-PDF accuracy and hardware support require
verification in the selected environment. Test fixtures and prior runs do not
certify all documents or an untested deployment.
