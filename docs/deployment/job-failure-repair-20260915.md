# Parse job failure repair, 2026-09-15

Job `job_965884e72a8d46fda9d6d2cdcf0c7eb0` exhausted three attempts after
approximately 139 minutes. Two independent defects contributed to this result.

## Causes and fixes

### The worker rejected a commit while still holding its locks

Each attempt produced a parser result, then failed with `FENCE_EXPIRED` while
committing the recovered source. The final attempt retained 15 pages, 2,575
blocks and 26 output files. Source validation, sealing and quality checks ran
inside a transaction that held the job/task locks for longer than the
60-second lease. Those same locks prevented the heartbeat from renewing it.

`src/packages/jobs/queue.py` now retains proof of a successful, unexpired fence check
only for that exact SQLAlchemy transaction and lease identity. Repeated checks
under continuously held locks still validate status, fence, control epoch and
document lifecycle. Releasing the transaction or rolling back a savepoint
invalidates the proof. Lease durations and reclaim rules are unchanged.

The original deployed image reproduced the failure using the exact retained
parser output in an isolated PostgreSQL database: the final transaction took
90.441 seconds and failed. The same replay with only the queue fix took 69.237
seconds and committed successfully. Both runs dispatched zero translation
requests.

### Docker Model Runner discarded Paddle's context setting

Unloading an idle Paddle runner during local translation handoff removes DMR's
runtime configuration. Subsequent Paddle startup used its model default of
131,072 tokens instead of the Compose setting of 8,192. Engine logs showed a
2.25 GiB KV-cache requirement against approximately 0.74 GiB available. Every
page's model recognition failed; deterministic native-text recovery produced
the retained output with quality warnings.

The Docker-built backend's `translation_startup.py` now caps the identified
Paddle architecture at 8,192 tokens before vLLM initializes its cache. It
preserves smaller limits, handles the final effective duplicate argument and
supported numeric suffixes, and bounds automatic limits. Other model types are
unaffected. It does not restore DMR configuration during unload, because that
operation eagerly reloads a model and defeats the GPU handoff.

## Recovery and preservation

A verified backup preceded the live change:
`backup_a0aba67b148240b189e1614d1c724c8f` (88 files).

The failed job remains a historical record. Its verified final output was
copied into a fresh, linked recovery attempt after checking the original
source hash, document generation, task fence and result manifest. The recovery
records that it reused earlier parser output rather than performing fresh
recognition. No translation was requested by the original workflow.

- Recovery: `job_c1439bd479ad45e5b54d5d9bd246cd1c`, completed with warnings.
- Source: `src_bfc00a87a8fd47929e348adbb0a1d1f3`, 15 pages and 2,575 blocks.
- Publication: `job_ac1a44ad1ebc4a4e924514c275a37a48`, completed with warnings.
- Published artifact: `artifact_447f1646239c406388d9c4ad1cf93af6`.
- The original PDF hash remains
  `fa89e54e23c0cea5cbd9d24720db7647c61af299afdb9a170c7119160e6d207a`.
- The previous artifact remains readable. Quality warnings were preserved.

## Deployment and verification

The app and worker use a minimal layer over their previously running image;
only the queue module changed. Both installed copies match the committed
module. The default local app tag also points to this repaired image.

- App image: `bilingual-personal-pdf-app:lease-fix-20260915`, manifest
  `sha256:d4a2c799beabc0184c3328f4a0671cc585e8c2c8954a6c50aa31ad1e9dcc0f71`.
- Prior app image: `bilingual-personal-pdf-app:before-lease-fix-20260915`.
- Docker-built macOS backend:
  `local/paper-translation-mlx-translator:lease-fix-20260915`, manifest
  `sha256:010119bdefa11b3d30b1afb07b3b535ce67d5bd520cf739fe59835da89a13bc2`.
- Backend archive and previous runtime are preserved under
  `.agent/local-data/job-965884-repair-20260915/`.

The parser and worker were stopped while idle during backend replacement.
The MLX setup receipt was cleared, the complete Docker-built payload installed
in DMR's backend directory, and fresh image inference verified before renewing
the receipt. DMR continues to own and launch the backend process.

Verification evidence is retained in
`.agent/tmp/job-965884-repair-20260915/`:

- 78 PostgreSQL regression tests passed, including lock exclusion, lease expiry,
  transaction/savepoint boundaries, cancellation and parse-result commits.
- 70 backend, local-model and parser unit tests passed. An independent review
  also passed 34 focused tests after the duplicate-argument fix.
- With DMR's saved Paddle configuration absent, actual image requests returned
  exact `MLX 123` and `GPU 789` text with HTTP 200 and the expected model ID.
  The engine log recorded an 8,192-token context and successful cache startup.
- A controlled PDF passed the HTTP → PostgreSQL → worker → parser → DMR path
  in 70.81 seconds: `job_d47d95fc4a8e4afba7294b57337caa96`, status `succeeded`,
  one page, 14 source blocks, no unresolved coverage or page-parse failure.
  Raw Paddle recognition output was retained, the source hash matched, and
  DMR configuration remained absent. No translation permits were created.
  The temporary test document was deleted after its evidence was saved.
- Original-image and fixed-image replays, backup verification, recovery logs,
  deployment commands, image digests and source/artifact checks are retained.

This recovery restores the saved result with its existing quality warnings.
It does not establish perfect scientific-paper extraction or cloud-provider
acceptance. No real API key was read and no cloud model call was made.
