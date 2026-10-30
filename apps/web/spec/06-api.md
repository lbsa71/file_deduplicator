# HTTP API contract

## Visual-query implementation (ADR 0001)

`GET /api/v1/photos` accepts `filters`, a JSON object alongside the existing
`q`, `folder`, `duplicates`, `favorite`, and `trash` scope. Supported keys are
`people`, `people_mode` (any/all), `albums`, `tags`, `from`, `to`, `date`
(any/known/unknown), `favorite` (any/yes/no), `type` (any/image/video), and
`missing` (any/people/albums). Dates are inclusive YYYY-MM-DD values.
`GET /api/v1/facets` accepts the same scope and returns `people`, `albums`, `tags`,
and `years` as `{value,count}` arrays, plus `date_unknown` and `total`.

`GET/POST /api/v1/views` lists/creates the authenticated user's saved queries.
Create body: `{name,query}`. `PATCH/DELETE /api/v1/views/{id}` require `If-Match`.
PATCH preserves omitted fields. View JSON includes `id`, `name`, `query`, and
`revision`. Each query stores the same scope as photo listing, without pagination.

`POST /api/v1/selections` accepts either `{query}` or `{targets:[{id,revision}]}`
and returns `{id,count,created,expires}`. It freezes all matching IDs and revisions
for 30 minutes. `POST /api/v1/batch-plans` accepts `operation` plus one of
`selection_id`, `targets`, or `query`. It returns `id`, `revision`, `count`,
`state:ready`, and five preview examples. Operations: metadata with distinct
`set/reset/add/remove`, move with `folder_id`, trash, or restore.
`POST /api/v1/batch-plans/{id}/execute` requires `If-Match` and returns the existing
202 job contract. Results contain totals and per-photo outcomes. Plans are private,
expire, are claimed once, and do not reevaluate queries during execution.

`POST /api/v1/exports` also accepts `selection_id` instead of explicit `ids`;
the existing 1,000-photo/20-GiB limits still apply. Saved-view and selection writes
require an authenticated reader and CSRF; batch plans/execution require an editor.

## General conventions

Base URL: `/api/v1`. Same origin as the UI. JSON uses UTF-8, UTC RFC3339 audit
timestamps, UUID strings, and integer byte counts. Capture times have separate
precision/timezone semantics. Unknown fields in write payloads are rejected.
The implementation must ship a generated OpenAPI document matching this contract
and contract tests; the tables below are the normative first-release surface.

## Common rules

Authenticate all routes except login, a minimal login-CSRF bootstrap, and a
content-free liveness endpoint. See [authentication](04-auth.md). Mutations require
CSRF protection. Resource mutations require `If-Match`; creates and job submissions
require `Idempotency-Key`. Reusing a key with a different body returns 409; the
same key/body returns the original resource/job. Retain idempotency mappings for
seven days, with longer-lived upload/purge identity in their manifests. Document
expired keys and never silently recreate a purged upload.

Collections return `{items, next_cursor, total, snapshot_id, index_updated_at}`.
Default limit 100, maximum 200. Opaque cursors bind filters, sort, and a catalog
generation for 15 minutes. Expired snapshots return 409 `snapshot_expired`; UI
refreshes while retaining filters. Do not use unbounded offset scans. Record
responses include `revision` equal to the strong ETag value, capabilities, and
current relative path; they do not expose absolute host paths.

Errors: `{error: {code, message, request_id, details}}`. Never return stack traces,
passwords, hidden host paths, or unauthorized record details. Statuses: 400 malformed,
401 session required, 403 role/CSRF denied, 404 missing resource, 409 state/path
conflict, 412 stale revision, 413 too large, 415 unsupported upload type, 422 invalid
field, 428 missing precondition, 429 throttled, 503 storage/broker unavailable,
507 insufficient storage. `Retry-After` accompanies temporary throttling/outages.

Exceptions to `If-Match`: upload chunks use offset/digest preconditions;
finish/commit use durable manifest state and idempotency keys; upload/job cancel,
job retry, logout, and session revocation use their explicit state machines.
These operations never bypass resource preconditions for the underlying photo
or folder mutation. Selection expiration returns 409 `selection_expired`.
Login/logout, CSRF bootstrap and session revocation do not require idempotency
keys; login is rate-limited, logout/revocation are repeatable. Chunk identity is
its upload ID plus offset/digest. Other job-producing mutations require keys.

Accepted jobs persist their complete frozen IDs/revisions independently of
selection/cursor TTLs. Expiration prevents new submissions, not execution of work
already accepted. Accepted background operations return 202 with `{job_id, state, status_url}` and
Location. Queued revision failure appears in the job result with the same error
code as a direct failure. A 202 means accepted, not completed. A busy library
queues work; it must not report a skipped scan as successful.

## Session and library

| Method and route | Input / output | Role |
| --- | --- | --- |
| GET `/auth/csrf` | Bound anonymous/login or session CSRF token, no-store | Public |
| POST `/auth/login` | `{username,password}` → user, role, CSRF token; session cookie | Public |
| GET `/auth/session` | Current UID/name/role/capabilities/expiry, no-store | Reader |
| POST `/auth/logout` | Revoke current session, expire cookie; 204 | Reader |
| GET `/library` | ID, availability, counts by lifecycle/type, bytes, trash bytes, free space, freshness | Reader |
| GET `/capabilities` | Enabled codecs, upload limits, editable fields, supported actions | Reader |
| GET `/settings` | Sanitized operational settings, never secrets or password hashes | Admin |
| PATCH `/settings` | With settings ETag; settle interval, worker/cache limits, reconciliation interval | Admin |
| DELETE `/sessions/{session_id}` | Revoke a session; 204 | Admin |
| GET `/sessions` | Session IDs, user, times; no credential/token material | Admin |

Library root, identity, PAM service and role-group configuration are deployment
configuration and cannot be changed by the settings endpoint.

## Records, metadata, and media

| Method and route | Contract | Role |
| --- | --- | --- |
| GET `/photos` | Cursor page; `q`, `from`, `to`, `people`, `albums`, `tags`, `kind`, `favorite`, `folder`, `recursive`, `duplicates`, `sort` | Reader |
| GET `/photos/{id}` | Full record view, effective metadata, overrides, source summaries, revision, capabilities | Reader |
| GET `/photos/{id}/history` | Paginated audit history | Reader |
| GET `/photos/{id}/sources` | Paginated original source documents and provenance | Reader |
| PATCH `/photos/{id}/metadata` | `{set: {...}, reset: [field,...]}` + If-Match → mutation job | Editor |
| POST `/photos/{id}/placement` | `{mode:"manual",folder_id}` or `{mode:"automatic"}` + If-Match → job | Editor |
| DELETE `/photos/{id}` | If-Match → trash job for exactly this occurrence | Editor |
| GET/HEAD `/photos/{id}/original` | Original bytes/range; `download=true` requests attachment | Reader |
| GET `/photos/{id}/variants` | Variant keys, dimensions, state, URL/error/retry eligibility | Reader |
| GET/HEAD `/photos/{id}/variants/{level}` | Authorized bytes when ready; 202 JSON + Retry-After on miss | Reader |
| POST `/photos/{id}/variants/retry` | Retry failed derivatives for current content/recipe → job | Editor |
| GET `/photos/{id}/sidecar` | Portable JSON attachment for this record | Reader |

Media for trashed records requires `include_trashed=true` on the explicit resource
request; ordinary listing/stream routes exclude trash. Missing storage returns
503, not 404; a known missing file returns 409 `media_missing`. Do not disclose a
cached derivative for a record the current session cannot access.

HEAD never returns a body. For a missing variant it returns 202 and Retry-After
without enqueueing generation; GET enqueues. Ready HEAD returns the same content
headers as GET. Conditional originals use a content-hash ETag; derivative ETags
identify the exact recipe output. Range requests return 206 or 416 as appropriate.

Metadata input fields and limits:

| Field | Value / clear behavior |
| --- | --- |
| `title` | String ≤512 characters; null suppresses source title |
| `description` | String ≤16,384 characters; null clears |
| `capture_time` | `{value: ISO8601, precision: "date"\|"second"\|"subsecond"}` or null; offset optional, never inferred |
| `people`, `albums`, `tags` | Unique trimmed strings, ≤256 labels/field, ≤256 characters/label; [] clears |
| `favorite` | Boolean |
| `location` | Null or latitude [-90,90], longitude [-180,180], optional finite altitude_m |
| `display_rotation` | 0/90/180/270 |

The same field cannot occur in both `set` and `reset`. Reset removes the override
and resolves imported information/defaults. Reject NaN, infinite numbers, invalid
dates, unsupported precision/value combinations, and control characters in labels.
For example:

```http
PATCH /api/v1/photos/9698a512-5967-448f-83c7-204772ae5a95/metadata
If-Match: "current-sidecar-digest"
Idempotency-Key: unique-request-key
Content-Type: application/json
X-CSRF-Token: session-csrf-token

{"set":{"people":["Alma"],"favorite":true},"reset":["description"]}
```

## Folders and bulk actions

| Method and route | Contract | Role |
| --- | --- | --- |
| GET `/folders?path=...` | Directory details, breadcrumbs, capabilities, child folders, file counts, revision; `.` means library root | Reader |
| POST `/folders` | `{parent_id,name}`; parent is registered user folder/root; returns 202 job/result folder ID | Editor |
| PATCH `/folders/{id}` | `{name?,parent_id?}` + If-Match; no merge/overwrite → job | Editor |
| DELETE `/folders/{id}` | `{preview_revision}` + If-Match; trash whole user subtree after preview → job | Editor |
| POST `/selections` | Explicit `{records:[{id,revision}]}` or `{query,snapshot_id}` → frozen selection ID/count/revision, expires_at | Reader |
| POST `/selections/{id}/preview` | `{action,parameters}` → affected IDs/counts/bytes/conflicts/duplicate impact and preview revision | Reader |
| POST `/selections/{id}/actions` | `{action,parameters,preview_revision}` → job; verifies selection and record revisions | Editor |
| POST `/folders/{id}/preview` | `{action,parameters}` → subtree counts/bytes/conflicts and revision | Reader |

Folder name: one nonempty component, no `.`, `..`, separators, NUL/control chars,
reserved application names, trailing dot/space, or exFAT-forbidden characters.
Enforce encoded path/component length limits and case/Unicode-equivalent collision
checks before reserving. Request paths are decoded once and validated; no symlink
traversal, mount crossing, absolute paths, or filesystem paths in arbitrary bodies.

The protected `folders/` root has a persistent registered UUID, exposed as
`user_folders_root_id` by GET `/library`. It can be a creation parent but cannot
be renamed, moved, or trashed. The whole-library `.` root cannot be a creation
parent. Parent/name changes require the destination parent's revision as
`parent_revision`, rechecked with collision reservations during execution.

Actions: `move` (`folder_id`), `automatic_placement`, `trash`, `favorite` (`value`),
and `labels` (`field`, `add`, `remove`). Frozen selections retain per-record
revisions; attempts with stale members produce explicit per-item conflicts. The
API caps explicit selections at 1,000 records; query snapshots support larger
batches. Folder subtree operations are one recoverable unit; ordinary photo bulk
operations commit per item and may finish `partial`. Downloads use the export API.

## Upload protocol

| Method and route | Contract | Role |
| --- | --- | --- |
| POST `/upload-batches` | `{target_folder_id?,preserve_directories:false}` → batch ID, target policy, limits | Editor |
| GET `/upload-batches/{id}` | Owner/admin only: uploads, committed group IDs, record bindings, state | Editor |
| POST `/uploads` | `{batch_id?,relative_path,size_bytes,kind,target_folder_id?,sha256?}` → upload ID, assigned media record ID if applicable, chunk size, offset, expiry | Editor |
| GET `/uploads/{id}` | Durable offset, chunk digests, state, result binding; ownership checked | Editor |
| PUT `/uploads/{id}/chunks` | Raw bytes, Upload-Offset, Content-Length, X-Chunk-SHA256 → durable next offset | Editor |
| POST `/uploads/{id}/finish` | Verify total bytes and optional final digest; mark staged complete | Editor |
| POST `/upload-batches/{id}/commit` | `{groups:[{media_upload_id,metadata_upload_ids,album_upload_ids}]}` → publish ready occurrence groups and ingestion job | Editor |
| DELETE `/uploads/{id}` | Cancel uncommitted transfer, release reservation; committed media requires trash | Editor |

Chunk default 8 MiB, final chunk may be smaller. Contiguous append only; an exact
retry at an earlier offset/digest returns the existing offset, conflicting bytes
return 409. Acknowledgment follows durable write and manifest update. On restart
discard unacknowledged tail bytes and reconcile the manifest before accepting more.
Client resume verifies reselected file size and hashes of acknowledged chunks.
The server calculates each chunk digest itself before acknowledging it. Upload
`kind` is one of `media`, `takeout_json`, or `album_json`; validate JSON shape before
commit and preserve unknown fields. The server computes the final full content
hash regardless of whether the client supplies one.

Default limits: media 20 GiB/file, JSON 32 MiB/file, 10,000 upload entries/batch,
two active transfers/user. Advertise configurable limits before transfer. Validate
actual byte counts/type signatures and supported suffixes; retain source names
verbatim in provenance while publishing safe paths. JSON is a metadata input,
never a media record. Reject executable/HTML uploads and ZIPs in v1.

Publishing a group commits its media and declared metadata together; shared album
documents can be referenced by several groups. Separate groups can be processed
before the entire batch finishes. Later metadata-only commits bind to an existing
group/upload occurrence; reject ambiguous filename-only associations. Internal
record allocation is persisted before enqueue so retries cannot create a second
record. Same bytes in a different deliberate upload create a retained occurrence.

Omitting `batch_id` creates an implicit batch and returns its ID. Every upload
response includes `batch_id`. A batch target policy cannot change after its first
upload. Commit results (including retried results) return stable `group_id` and
record ID bindings. A metadata-only commit uses
`{existing_group_id,metadata_upload_ids,album_upload_ids}` instead of
`media_upload_id`; reject mixed forms, foreign-owned groups, and conflicting
bindings. Keep committed bindings in authoritative upload/source manifests after
partial-upload cleanup so late metadata can still address the occurrence.

## Trash, exports, and jobs

| Method and route | Contract | Role |
| --- | --- | --- |
| GET `/trash` | Cursor page of trash operations, counts, bytes, former paths, revisions | Reader |
| POST `/trash/{id}/restore` | `{target_folder_id?}` + If-Match → recoverable restore job | Editor |
| DELETE `/trash/{id}` | `{confirm_revision}` + If-Match → irreversible purge job | Admin |
| POST `/exports` | `{selection_id,include_metadata:false}` → original-file ZIP export job | Reader |
| GET/HEAD `/exports/{id}/download` | Authorized range-capable ZIP after completion | Reader |
| POST `/scans` | `{mode,scope}` → scan job; modes below | Editor/Admin |
| GET `/jobs` | Paginated relevant jobs, states and progress | Reader |
| GET `/jobs/{id}` | Progress, per-item outcomes, errors, next actions and stats | Reader |
| POST `/jobs/{id}/cancel` | Request cancellation at safe boundary | Owner/Admin |
| POST `/jobs/{id}/retry` | Retry failed/unprocessed items with fresh authorization | Owner/Admin |
| GET `/events` | Authenticated SSE, event IDs and bounded replay | Reader |

Upload and export status/content is visible only to its creator or administrator;
library-affecting job progress is visible to library readers. Viewers cannot retry
or cancel another user's mutation. Retry also requires the original action's role.

Scan modes: `reconcile`, `metadata`, `verify`, `catalog`, `thumbnails`. Scope is
`{record_ids:[...]}`, `{folder_id:...}`, or `{library:true}`. Editors may reconcile
selected records/user folders; other modes and full-library scans require admin.
Folder scopes snapshot descendant IDs. Reconcile includes newly arrived files.
Metadata reruns configured extraction/resolution; verify reads full content;
catalog rebuilds derived state; thumbnails rebuilds selected derived recipes.

Exports freeze selection and revisions, include originals byte-for-byte, and use
safe original filenames with record-ID suffixes on collisions. Include a manifest
mapping paths to record IDs/hashes; optional sidecars carry provenance and people/
location data. Warn about those included fields before metadata export. Limit
default exports to 20 GiB and 5,000 records; check space reservations before work.
Exports expire after 24 hours. Modified/missing sources fail affected exports rather
than silently mixing revisions. Temporary exports are disposable, never originals.

SSE events: `job.updated`, `record.changed`, `folder.changed`, `variant.ready`,
`library.availability`, `catalog.updated`, and `reset_required`. Events contain IDs
and revisions; clients refetch authorized details. Replay lasts 15 minutes;
expired cursors receive `reset_required`. Polling at 2–10 seconds with backoff is
the fallback. Events are hints; HTTP/resource state remains authoritative.
