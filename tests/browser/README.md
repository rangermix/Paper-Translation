# Browser checks

Run from the repository root. Install the locked frontend dependencies with
`npm --prefix src/apps/web ci`, then start a local frontend in a separate terminal:

```sh
npm --prefix src/apps/web run dev -- --port 5181 --strictPort
```

Run the default suite against that frontend. Its application tests mock API
responses; live-instance and historical-artifact checks skip unless enabled.
Use a new output directory for every run:

```sh
LIBRARY_BROWSER_URL=http://127.0.0.1:5181 \
LIBRARY_BROWSER_OUTPUT=.agent/tmp/browser-<unique-run> \
npm --prefix src/apps/web run test:browser
```

`npm --prefix src/apps/web run test:browser -- --list` collects the suite without
requiring a local evidence archive.
To use an already installed Google Chrome, set `LIBRARY_BROWSER_CHANNEL=chrome`;
omitting it keeps Playwright's bundled Chromium default. Keep the same explicit
test URL and output directory.

## Live acceptance instance

Live checks require both `LIBRARY_LIVE_BROWSER=1` and an explicit
`LIBRARY_BROWSER_URL` pointing to a disposable, designated acceptance instance.
They never choose port 8080 on their own. The `live-library`, `live-resilience`
and `live-storage` checks create or edit document records; upload flows select
source-only processing and do not authorize translation-provider requests.
The `job-presentation-live` check reads existing jobs without changing them.
Run these checks only after preparing the corresponding Compose instance.

`live-storage.spec.ts` uses `LIBRARY_LIVE_RECEIPT` to locate the JSON receipt
written by `live-resilience.spec.ts`, or looks for it under the current output
directory's `live/` subdirectory. These runtime checks do not certify a schema
version or real-provider behavior.

`reader-font-cache.spec.ts` is a read-only check against two published `reader-v13`
artifacts with code blocks. Set `LIBRARY_READER_CACHE_URL` to a real API HTTP
server and `LIBRARY_READER_CACHE_FIRST` / `LIBRARY_READER_CACHE_SECOND` to distinct
`/artifacts/<id>/index.html` paths. It uses a fresh Chromium context without request
interception and records CDP transfer/cache evidence for all six bundled font
variants across readers, reloads and preference changes. A static file server
does not exercise the API's shared font redirects and is not sufficient here.

## Historical and independently authored artifacts

Each variable below enables its corresponding offline browser checks. Values
are paths accepted by the repository's browser path helper. If no value is
provided, the check skips with an explanation. An explicitly supplied missing
or invalid artifact remains a failure.

| Variable | Required input |
| --- | --- |
| `LIBRARY_CAPTION_EVIDENCE` | Directory with `response.json`, `single.html` and `bundle/index.html` for the caption math corpus |
| `LIBRARY_COMPLETE_MATH_EVIDENCE` | Directory with the complete 86-reference math corpus and the same file layout |
| `LIBRARY_HOSTILE_EVIDENCE` | Directory with `verification.json`, `single.html` and `bundle/index.html` |
| `LIBRARY_ANCHOR_EVIDENCE` | Directory with `reader-v1/` and `reader-v2/`, each containing `response.json`, `single.html` and `bundle/index.html` |
| `LIBRARY_ENLARGEMENT_EVIDENCE` | Directory with `reader-v1.html` and `reader-v2.html` for the authored long-code corpus |
| `LIBRARY_COMPLEX_EVIDENCE` | Directory containing the independently authored complex export evidence |
| `LIBRARY_READER_FONT_EVIDENCE` | Directory with `single.html` and `bundle/index.html` generated using `reader-v7` and the authored fixture in `tests/unit/test_reader_v5.py` |
| `LIBRARY_READER_SIDENOTES_EVIDENCE` | Directory with `single.html`, `bundle/index.html`, `table.html` and `native.html`, generated with `reader-v9` from `sidenote_fixture()`, `table_reference_fixture()` and `native_sidenote_fixture()` in `tests/unit/test_reader_sidenotes.py`; covers contextual notes/references, authored native PDF markers, offline exports, keyboard, mobile, print and no-JavaScript fallback |
| `LIBRARY_DRAFT_HTML` | The actual worker-generated unfinished-draft HTML file |
| `LIBRARY_READER_V11_EVIDENCE` | Directory with `single.html` and `bundle/index.html`, generated with `reader-v11` from `rich_sidenote_fixture()` in `tests/unit/test_reader_v11.py`; covers original title metadata, nested citations, printed/explicit footnotes, collected notes, offline exports, keyboard, mobile, print and no-JavaScript navigation |
| `LIBRARY_READER_THEME_EVIDENCE` | Directory with `3.0/` and `4.0/` subdirectories, each containing `published/index.html`, `single.html` and `bundle/index.html` generated with `reader-v13` from `sidenote_fixture()` / `typography_fixture()` in `test_reader_theme.py`; serve this directory over HTTP and set `LIBRARY_READER_THEME_URL` for the published font-loading check. Covers live themes, bundled fonts, independent font/line-height preferences, unavailable storage, mobile, print and no-JavaScript reading |
| `ORIGINAL_ONLY_READER_ROOT` | Directory containing `reading.html` and `artifact/index.html` for the source-only workflow |

These artifacts are evidence, not replacement application fixtures. Skipped
checks do not establish offline-reader or live-runtime acceptance.
