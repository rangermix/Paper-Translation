# Task kinds and relationships

This is the task-center product contract. A row represents a meaningful operation
on one PDF or the instance, such as uploading, parsing, translating, deleting or
backing up. One document
can have several different operations; sharing a document or title does not make
those operations duplicates.

## Main tasks, steps and attempts

| Concept | Meaning | Where it appears |
| --- | --- | --- |
| Main task | An operation explicitly requested by the user, or started automatically by their chosen workflow | One row in the task center and history |
| Internal step | Work needed to complete a main task, with no separate user intent | Inside that main task's details |
| Related main task | A distinct operation started from another operation's result | Its own row, with a link to the preceding or following main task |
| Attempt | One execution of a worker step or provider request, including a permitted retry | In the owning step's execution records |

Containment and sequence are different relationships. Upload inspection belongs
to upload. Parsing follows upload, but is a separate main task. Translation and
publication are also separate main tasks even when the selected workflow starts
them automatically. An automatic trigger does not by itself make work an
internal step.

## Main task kinds

The operation is the user-facing kind. The execution stages below are existing
backend identifiers; one main task may contain several stages or worker tasks.

| Operation | Execution stage(s) | Included work | Separate related operations |
| --- | --- | --- | --- |
| Upload PDF | `inspect` for the durable PDF inspection | File transfer, integrity/PDF inspection, accepting the upload, and automatic bibliographic metadata lookup | Parsing the accepted PDF |
| Parse source | `parse` | Extraction, deterministic source correction, bounded recovery, source coverage/content checks and source-result preparation | Translation, or publication of a source-only result |
| Translate | `translate` | Preparation/context/terminology, translation units, provider requests, deterministic validation, translation content checks and optional automatic sealing | Publication when selected |
| Translate selected text | `candidate` | Preparation and requests for the selected candidate scope, with their validation | Applying a candidate is an editor action, not another translation task |
| Review meaning | `semantic_review` | Optional model-assisted semantic checks and saved findings | Later user-requested edits or translation |
| Publish | `publish` | Building and validating immutable reader files, then switching the current publication and updating search, or retaining a preview as requested | Later export, rebuild or history switch |
| Rebuild reader | `rebuild` | Rendering an existing sealed revision with the selected template and updating the publication/index as requested | Translation is not rerun |
| Switch historical publication | `index` for the subsequent index update; operation `rollback` | Switching the current pointer to a retained artifact and synchronizing search | A later switch is a new operation |
| Export | `export` | Preparing the requested HTML or resource bundle from a draft or published artifact | Repeated explicit exports are separate operations |
| Delete document | `cleanup` | Making content unavailable, cancelling/fencing work and removing eligible files | No additional top-level file-cleanup task |
| Refresh bibliographic metadata | `metadata_lookup`, with `inspect` when native PDF evidence is needed | Explicit refresh, supporting inspection and metadata lookup | Automatic lookup during upload/parse stays inside its owning task |
| Check content | `quality_check` | An explicitly requested deterministic content check, including validation needed by a manual seal | Checks automatically run by parse or translation are internal steps |
| Test provider connection | `provider_test` | The explicitly confirmed connection request and its outcome | Saving settings does not create or run this task |
| Back up / restore the instance | `backup`, `restore` | One maintenance command and its completion/failure receipt | Other maintenance commands are separate operations |
| Maintain the instance | `maintenance` | Migration, verification, backup verification, retention, controlled seeding or an explicit administrative command; the receipt preserves its operation | The command's internal work is not another main task |

Backup, restore, verification and storage maintenance currently run through the
maintenance service. Their task-center receipts are written after the command
finishes, when the active database can accept them, including after a restore.
They do not provide live worker progress. Volume initialization has no database
task receipt. These instance tasks have no document owner.
Ordinary synchronous edits (title, tags, star/archive, settings, source or segment
edits, candidate selection, sealing and unpublishing) keep their existing revision
or event records; they do not each require a new background-task row. A check
run during a manual seal currently leaves a standalone check receipt when there
is no enclosing background task. That receipt reports the checker outcome;
the immutable revision records whether sealing succeeded.

## Internal steps

| Step | Owner |
| --- | --- |
| PDF inspection | Upload; or an explicitly requested metadata refresh that needs new PDF evidence |
| Automatic metadata lookup | The upload, parse or metadata refresh that requested it |
| Recovery / deterministic correction (`recovery`) | Parsing |
| Source coverage/content checks | Parsing |
| Paper preparation, translation units and their provider requests | Translation or selected-text translation |
| Automatic translation content checks (`quality_check`) | Translation or the operation that requested the check |
| Reader construction / resource validation | Publication, rebuild or export |
| Search-index synchronization (`index`) | Publication, rebuild or historical-publication switch |
| File cleanup | Document deletion |

An internal step can have nested steps and multiple attempts. Those records remain
inspectable, with actual model identities, timings, redacted logs, costs and
outcomes. They must not become extra top-level history rows when a worker starts,
finishes or retries them. Older steps with no reliable owner remain inspectable;
ownership must not be guessed from a shared title or nearby timestamps.

## Workflow examples

An upload with automatic translation and publication creates four main tasks:

```text
Upload PDF -> Parse source -> Translate -> Publish
  inspection   recovery        preparation   reader build
  metadata     source checks   units/checks  index update
```

The first line shows links between main tasks. The lines below show internal
steps. Upload and upload inspection are one task, not two. The four main tasks
have independent states: upload can succeed while parsing runs; translation can
finish while publication is still pending.

A source-only workflow is `Upload PDF -> Parse source -> Publish`. If the user
later chooses translation, it creates a new translation main task linked to the
source or previous translation it uses. Its optional publication is another main
task. Re-parsing an existing PDF likewise creates a new parse main task; it does
not reopen the original upload.

Deleting six library entries creates six deletion main tasks, one per document.
Each includes its file cleanup. A batch selection is not an extra seventh task.
Two separate entries with the same paper title are still separate documents and
must have distinguishable receipts. A repeated delivery of the same idempotent
request must return the existing operation rather than create another one.

Resuming or safely retrying an existing task keeps its task identity and records
another attempt. An explicit new parse, translation continuation, publication or
export creates a new main task. Unknown paid-provider outcomes remain unresolved
until explicitly reconciled or authorized; grouping never permits automatic
redispatch.

## Listing, status and history

- Lists, counts, filters and pagination operate on main tasks. Details separate
  internal steps from links to other main tasks. A task must not appear both as a
  main row and as another task's internal step.
- A main task's displayed state includes its internal steps, not the states of
  linked main tasks. Active work and unresolved requests remain discoverable even
  after an earlier internal step finishes. Controls still target the actual
  execution record and retain its generation, CAS, fence and lease checks.
- Content-quality findings and recoverable metadata/quality-check failures are
  warnings. Execution failures, invalid files/paths, version conflicts and missing
  external-processing authorization retain their existing handling.
- Progress, duration, model identity and cost belong to their recorded scope.
  Do not present one child's values as totals for the whole operation, or add the
  same request cost both to a main task and to its related successor.
- Clearing completed history changes visibility only. Internal history remains
  available in details and through the include-cleared view. Active, waiting or
  unresolved work stays visible; independently linked tasks keep their own states
  and visibility.
- Deleting a document must not resurrect already-cleared completed history when
  fencing its old jobs. Deletion receipts use a safe identifier and timestamp;
  erased titles, filenames, content and provider evidence remain redacted.

## Implementation and verification boundary

This contract distinguishes the presentation model from stored execution
records. A database `Job`, worker `Task` and `Attempt` are not interchangeable
with a task-center main task. In particular, existing `parent_job_id` records
include both internal work and automatically started follow-up operations;
the kind and relationship must determine their presentation.

Use explicit upload, document, draft, publication and job identifiers to link
operations. Existing history must be interpreted without rewriting installed
migrations, sealed snapshots or published artifacts. Missing historical links
must remain unknown rather than being reconstructed from similar filenames.

The presentation rules live in [jobs/hierarchy.py](../src/packages/jobs/hierarchy.py)
and the [jobs API](../src/apps/api/workflow.py). Existing unowned records remain
visible rather than being merged without evidence. The browser uploads bytes
before finalization creates the durable inspection job; transfer progress and
inspection belong to the same upload, with no second upload history job.

Verify both new and existing records: upload plus inspection appears once; parsing,
translation and publication appear independently and are linked; automatic
checks/indexing remain internal; retries keep the same main task; explicit new
operations stay separate; deletion preserves cleared-history visibility and
redaction. Source changes, automated regression results and the selected running
instance must be reported separately. This document alone does not certify a
deployment.
