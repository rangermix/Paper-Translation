# Optional cost controls frontend

Owner /root/web_ui; root backend/API, IR config/billing, acceptance independent QA. Only mock browser requests from19174;18088/18086/8080 untouched. Browser plugin unavailable; existing isolated Playwright. No real Provider calls.

## Confirmed contract

Provider effective cost_control_enabled false for new/unconfigured, missing old profile flag preserves true. token_limits_defaults and all three effective inputs are server-visible. UI uses actual custom values first, then published defaults32768/8192/2000. PUT sends explicit flag/current three values; no readonly defaults object. Claude effective version displayed2023-06-01 when server default applies. Reset and undo affect exactly three limits, preserving pending key/URL/model/price/cost mode, no implicit save.

Four new request entrypoints omit budget when disabled; external/source/experimental consent and profile hashes remain. Jobs use their frozen cost mode, never current settings. Nullable money shows 未计算; off task budget shows 未限制. Unknown retry retains existing risk checkbox (wording includes same bound service), no extra external API field; on requires budget/off omits.

## State and evidence

Production frontend implemented; build index-wOnFKMv2.js, CSS unchanged.16new+57existing browser contracts73passed39.1s,13unit passed,tsc+Vite passed. Last test-only refinement reloads each viewport and scrolls top so expanded limit values are actually asserted and image geometry reflects top;1case passed1.7s. Independent review pending acceptance at19174, production candidate ready for parent build.

Exact before snapshots/source diff and AUTHOR_QA: evidence/cost-controls/frontend. Current desktop/mobile images viewport-top-final. First intentional red: cost checkbox absent. First post-implementation test failure was erroneous expected server-only price revision; corrected public-field assertion, unchanged production. Both histories retained.

Author screenshot overwrite incident: earlier existing tests defaulted to historical paths. Two native images restored from independent exactSHA copies; three old Settings author images unavailable, expected hashes/reports preserved and correction explicitly marks them non-reverifiable. Independent actual UI evidence untouched. All involved tests now default unique/test output paths or explicit run env; correction evidence/cost-controls/frontend/screenshot-overwrite-correction.json. Do not substitute new pictures as old proof.

## Final delivery

73 final browser contracts passed40.5s after only punctuation cleanup,13unit passed,tsc+Vite passed. Final asset index-6muiN2d7.js; management CSS unchangedBEgjW6yP, reader-v1 unchanged. Exact FINAL_AUTHOR_QA.json and source-final.diff recorded. Acceptance independently16contracts9.8s plus desktop/mobile visuals no blocking finding; only pointed out duplicate punctuation, now removed.19174 precise ownPID69520 stopped; final process/listener0 (immediate stale TCP response retained). New actualAPI/runtime review remains parent/acceptance18089. No remaining frontend changes requested.
