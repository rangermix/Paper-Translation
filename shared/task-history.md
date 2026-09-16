# Clearing task history

The task center can clear all finished tasks from its default list. The confirmation explicitly covers all pages and filters, including success, completion with warnings, partial completion, failure, and cancellation. Users can select **显示已清除历史** to include retained records again.

The task center lists only top-level jobs (`parent_job_id` is null), including when searching, filtering, paging, or showing cleared history. Open a parent task to page through its child tasks and view their details/logs, including children beyond the first 100 returned in the parent snapshot. Clearing history still covers eligible parent and child records.

Clearing changes list visibility only. Documents, sources, translations, artifacts, task details, model/time snapshots, logs, attempts, events, and billing records remain intact. Active or waiting jobs, leased tasks, and jobs with reserved or unknown dispatch permits cannot be cleared. A job that later changes generation becomes visible again. Jobs excluded from a clear operation remain visible when their outstanding work settles.

## API

- `GET /api/v1/jobs/history`: returns `generation`, `clearable_count`, and a Settings-generation ETag. The count is global, independent of search, filters, and pagination.
- `POST /api/v1/jobs/history/clear`: requires `{"confirm":true}`, `If-Match`, and `Idempotency-Key`. Re-evaluates eligibility at confirmation time and returns `generation` and the actual `cleared_count`. Missing preconditions return 428; stale generation returns 412; invalid confirmation returns 422; maintenance blocks the operation. An idempotent replay returns the original count without clearing newer jobs.
- `GET /api/v1/jobs`: excludes cleared, unchanged finished jobs before filtering and pagination. `include_cleared=true` includes them. Detail and log endpoints remain readable.
- `GET /api/v1/jobs?top_level_only=true`: filters to jobs without a parent before pagination. The task-center UI always sends this flag. The API default remains false for callers that need all jobs; `parent_job_id` continues to select a parent's immediate children.

Schema 13 adds the nullable `jobs.history_cleared_generation` column without rewriting historical evidence. Clear uses the existing lifecycle transaction lock and Settings generation CAS; it does not change job generations or dispatch state. The column is included in normal database backups. Apply the migration before starting the updated app and worker.
