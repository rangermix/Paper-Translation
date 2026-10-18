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
| `LIBRARY_READER_V5_EVIDENCE` | Directory with `single.html` and `bundle/index.html` generated using `reader-v5` and `reader_fixture()` in `tests/unit/test_reader_v5.py` |
| `LIBRARY_READER_FONT_EVIDENCE` | Directory with `single.html` and `bundle/index.html` generated using `reader-v7` and the authored fixture in `tests/unit/test_reader_v5.py` |
| `LIBRARY_READER_SIDENOTES_EVIDENCE` | Directory with `single.html`, `bundle/index.html`, `table.html` and `native.html`, generated with `reader-v9` from `sidenote_fixture()`, `table_reference_fixture()` and `native_sidenote_fixture()` in `tests/unit/test_reader_sidenotes.py`; covers contextual notes/references, authored native PDF markers, offline exports, keyboard, mobile, print and no-JavaScript fallback |
| `LIBRARY_DRAFT_HTML` | The actual worker-generated unfinished-draft HTML file |
| `LIBRARY_READER_V11_EVIDENCE` | Directory with `single.html` and `bundle/index.html`, generated with `reader-v11` from `rich_sidenote_fixture()` in `tests/unit/test_reader_v11.py`; covers original title metadata, nested citations, printed/explicit footnotes, collected notes, offline exports, keyboard, mobile, print and no-JavaScript navigation |
| `LIBRARY_READER_THEME_EVIDENCE` | Directory with `3.0/` and `4.0/` subdirectories, each containing `published/index.html`, `single.html` and `bundle/index.html` generated with `reader-v13` or `reader-v14` from `sidenote_fixture()` / `typography_fixture()` in `test_reader_theme.py`; serve this directory over HTTP and set `LIBRARY_READER_THEME_URL` for the published font-loading check. Covers live themes, bundled fonts, independent font/line-height preferences, unavailable storage, mobile, print and no-JavaScript reading |
| `LIBRARY_READER_NAVIGATION_EVIDENCE` | New `reader-v14` fixtures generated by [reader_navigation_evidence.py](../runtime/reader_navigation_evidence.py). Set `LIBRARY_READER_THEME_URL` to its loopback server, which maps `/artifacts/3.0/`, `/artifacts/4.0/` and `/artifacts/long/` to the corresponding publication. Checks bilingual labels, stable anchors, search return validation, no-JavaScript links, offline formats and mobile/print navigation, including a 42-section six-level outline |
| `ORIGINAL_ONLY_READER_ROOT` | Directory containing worker-generated `reading.html` and `artifact/index.html` with retained authors, affiliations and references plus translated body text |

These artifacts are evidence, not replacement application fixtures. Skipped
checks do not establish offline-reader or live-runtime acceptance.

To reproduce the new reader checks, use the locked Python test environment to run
`python tests/runtime/reader_navigation_evidence.py .agent/tmp/<run>/reader-v14`.
Serve the resulting directory with the same script and `--serve 5182`, then set
both evidence variables above to that directory and run `reader-theme.spec.ts`
and `reader-navigation.spec.ts`. Generate into a new directory each time; the
generator does not overwrite evidence or modify an existing publication.

## Recreate conditional inputs

Run the following generators from the repository root with `PYTHONPATH=src` in
the locked Python test environment. Give each invocation a new output directory.
Mount current `src/`, `tests/` and `res/` read-only when reusing an older test image;
the image supplies dependencies, not the source revision under test. Keep output
under a dedicated `.agent/tmp/<run>/` mount. Do not use the installed library's
database, provider configuration or data volumes.

| Generator | Inputs and browser variables |
| --- | --- |
| [reader_compatibility_evidence.py](../runtime/reader_compatibility_evidence.py) `OUTPUT` | Generates version-correct `v5`, `v7`, `v9`, `v11` and `v14` directories from tracked authored fixtures. Map them to the matching reader variables above. Use `reader_navigation_evidence.py OUTPUT/v14 --serve PORT` for both v14 HTTP suites. |
| [independent_content_evidence.py](../runtime/independent_content_evidence.py) `OUTPUT --source-revision COMMIT --image-id DIGEST` | Generates `complex/` (both complex and enlargement variables) and `hostile/`. No database or network is needed. |
| Same generator with `--math-input REVIEWED_INPUT` | Additionally generates `caption/`, `all/` and `anchor/`, for the caption, complete-math and anchor variables. Requires the archived `response.json`, `remaining-math-reviewed-plans.json` and original `data/` assets mounted read-only. Source and image hashes are checked; the 86 recorded decisions and pixel crops are replayed through current code. This does not constitute a new human review or model parsing run. |
| [reader_font_cache_evidence.py](../runtime/reader_font_cache_evidence.py) `OUTPUT --confirm-disposable-instance` | Run with the disposable API instance's data volume and database configuration. Registers two authored v13 artifacts with code blocks. `receipt.json` supplies the two artifact paths for `LIBRARY_READER_CACHE_FIRST` and `SECOND`; point `LIBRARY_READER_CACHE_URL` at that actual API server. This checks API asset delivery/cache, not the publication workflow. |
| [live_browser_evidence.py](../runtime/live_browser_evidence.py) | Run `--help` for the explicit disposable-instance confirmation and revision arguments. Generate `draft` first, then `original`, using the isolated instance's real API and worker. Set `LIBRARY_DRAFT_HTML` to the draft `reading.html`, and `ORIGINAL_ONLY_READER_ROOT` to the original-content output directory. The IR is authored; queueing, snapshots, publication and export are actual application operations. |

For live checks, create a separate Compose project using `compose.example.yaml`
and a temporary override with loopback ports, fresh named volumes and explicit
image bindings. Start only the required named services; never use a profile-wide
`up`. Upload checks need the native PDF inspector. Model services are not required
for their intake/persistence assertions: when inference is unavailable the later
parse job must remain honestly failed or pending, not be fabricated as successful.
Disable external provider/model egress for this fixture-only run.

Run `live-library.spec.ts` and `live-resilience.spec.ts` first. Then supply the
new resilience receipt via `LIBRARY_LIVE_RECEIPT` to `live-storage.spec.ts`, and
run `job-presentation-live.spec.ts` against the jobs created in this same instance.
Keep each run's JSON report and any first-failure evidence. Reconcile conditional
cases by file and test title; repeated runs of a case are not additional coverage.
Afterward remove only that disposable project's containers and volumes using the
same explicit project and configuration arguments.
