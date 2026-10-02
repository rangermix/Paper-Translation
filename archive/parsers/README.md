# Archived parser integrations

PaddleOCR-VL, TeleOCR and Xiaomi-OCR-0 are retained here as source material for a
future restoration. They are unavailable for new parsing, absent from the active
catalog, dependency lock and application image. `.dockerignore` excludes this
entire directory. Docling and Granite inference were removed; their implementation
can be retrieved from Git history before `1b7afe6`.

This is an archive, not a supported alternate deployment. Restoring an adapter
requires a new reviewed contract and integration with the current neutral source
builder. The copied native inference fragments need their historical imports,
runtime configuration and dependencies; they are deliberately not importable from
`src/`. The archived pinned manifests contain no downloaded weights.

- `src/packages/parsers/pdf_paddleocr.py`: Paddle's layout/crop recognition adapter.
- `src/packages/parsers/native_vision.py`: TeleOCR native Transformers inference
  and region recognition fragments.
- `src/packages/parsers/vlm_output.py`: historical TeleOCR/OTSL and Xiaomi Markdown
  decoding, before the new rich full-page decoder.
- `deployment/`: model manifests and native Paddle/TeleOCR dependency locks.
- `src/tools/export_parser_model.py`: historical Paddle packaging tool.

Saved profile identities, existing sources, translations and publication files do
not depend on these files. The runtime retains historical names for display and
returns an unavailable-parser result for queued retired choices without changing
their snapshots. Explicitly choose an active parser to create a new task.
