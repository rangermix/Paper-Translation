# Prepared final candidate build

Do not execute this recipe until the coordinating root agent confirms the API,
source correction, parser, frontend, tests and harness freeze. A successful build
creates review candidates; it does not close the milestone gates. Preserve the old
8080 project and its PostgreSQL volume. Never run a new PostgreSQL base against
that existing data volume.

From the project root, after all review/test changes have landed:

```powershell
$releaseLabel = 'coordinated-' + (Get-Date -AsUTC -Format 'yyyyMMdd-HHmmss')
$sourceTree = .venv/Scripts/python.exe .agent/harness/acceptance.py fingerprint
$sourceCommit = git rev-parse HEAD
$appTag = 'bilingual-personal-pdf-app:' + $releaseLabel
$parserTag = 'bilingual-personal-pdf-parser:' + $releaseLabel
$dbTag = 'bilingual-personal-pdf-db:' + $releaseLabel
.venv/Scripts/python.exe .agent/harness/acceptance.py run --id ($releaseLabel + '-app-build') --kind compose --timeout 1800 -- docker build --file deployment/images/app.Dockerfile --tag $appTag --build-arg "SOURCE_COMMIT=$sourceCommit" --build-arg "SOURCE_TREE_SHA256=$sourceTree" .
if ($LASTEXITCODE -ne 0) { throw 'App candidate build or source stability failed' }
.venv/Scripts/python.exe .agent/harness/acceptance.py run --id ($releaseLabel + '-parser-build') --kind compose --timeout 1800 -- docker build --file deployment/images/parser.Dockerfile --tag $parserTag --build-arg "SOURCE_COMMIT=$sourceCommit" --build-arg "SOURCE_TREE_SHA256=$sourceTree" .
if ($LASTEXITCODE -ne 0) { throw 'Parser candidate build or source stability failed' }
.venv/Scripts/python.exe .agent/harness/acceptance.py run --id ($releaseLabel + '-db-build') --kind compose --timeout 1800 -- docker build --file deployment/images/database.Dockerfile --tag $dbTag --build-arg "SOURCE_COMMIT=$sourceCommit" --build-arg "SOURCE_TREE_SHA256=$sourceTree" .
if ($LASTEXITCODE -ne 0) { throw 'Database candidate build or source stability failed' }
if ((.venv/Scripts/python.exe .agent/harness/acceptance.py fingerprint) -ne $sourceTree) { throw 'Source changed during the candidate set' }
docker image inspect $appTag $parserTag $dbTag
docker run --rm --network none --read-only --entrypoint python $appTag -c "from packages.parsers.models import parser_version; from packages.domain.db import SCHEMA_VERSION; print(parser_version(), SCHEMA_VERSION)"
if ($LASTEXITCODE -ne 0) { throw 'App parser-manifest/schema packaging smoke failed' }
```

Use the immutable image IDs returned above for the next fresh-project offline
roundtrip and process fault runs. Preserve every previous evidence directory.
Run `scan_candidate_image.py` once per image **sequentially** because its local
Trivy cache is exclusive; emit SBOMs and match saved archive layers to each exact
image ID. Repeat the controlled English and Chinese parser smoke offline if any
parser closure changed. Ask the already assigned independent agents to review
their final-version behavior and register concrete scenario proof only.

The real-provider runner remains default-off. This recipe never authorizes a
Provider call or spends a testing budget. Unknown-cost and incomplete paper-gold
gates remain separate from local build success. The final source fingerprint must
include these instructions and all tests before the first build starts.
