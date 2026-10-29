# Jobs, reconciliation, and operation

## Process boundaries

Build the UI in `apps/web/`; keep API, auth adapter, and web tests there too.
Reuse the installable `photoflow` package for record rules and mutations. Move
shared domain code into `packages/` only when necessary, retaining CLI import
compatibility. Do not create a second implementation of placement or metadata
resolution in TypeScript.

Deploy a static UI/reverse proxy, unprivileged Python API, a single coordinator,
bounded decoder workers, and the narrow PAM broker. Keep one configured ExifTool
version/reader policy across CLI and web. If configured ExifTool becomes
unavailable, mark extraction unavailable and retain prior results; do not replace
them with the current no-reader adapter's empty metadata result.

## Durable work

Persist mutation requests before acknowledgment. A job records schema/library ID,
actor, idempotency key, action/parameters, expected revisions, attempt, state,
progress, result references, and error codes. States:

```text
queued → running → succeeded
                 → partial
                 → failed
                 → cancelling → cancelled
```

`waiting_for_storage` and `waiting_for_lock` are queued reasons, not successful
completion. Recovery discovers in-flight operations from journals before normal
work. Cancellation finishes an in-progress atomic/recoverable step, then stops
before the next item; completed changes remain visible. A folder rename finishes
recovery as one unit. Never kill the coordinator mid-move to implement Cancel.

Validate user authority and preconditions again on execution. Revoked authority
blocks new work; recovery still completes already-started operations safely.
Retries apply only to failed/unprocessed items and report outcomes already
committed. Transient failures use bounded backoff; malformed data and conflicts
require correction. Keep operational job results 30 days by default, durable
record histories and purge receipts longer as authoritative evidence.

## Upload completion and capacity

Stage uploads on the library filesystem beneath protected state so publication
can use same-filesystem no-overwrite operations. Reserve declared bytes per user
and volume; count pending uploads and exports, not merely current free space.
Default reserve floor: the greater of 2 GiB or 2% of volume size. Handle ENOSPC
at every write, since external SMB clients can consume space after reservation.
Retain acknowledged chunks on failures and report the resumable offset.

Expire uncommitted idle uploads after seven days, with UI expiry warning and a
cleanup audit entry. Expiry deletes only application-created staging data;
committed originals follow trash policy. Active jobs/uploads prevent destructive
folder operations affecting their destination. Client cancellation never deletes
an original that was already committed.

## Discovery and force rescan

Watch the server's locally mounted library recursively, coalescing relevant
changes for 60 seconds. Process settled groups at least every five minutes during
continuous activity; this bound never declares an incomplete upload ready.
Browser publication provides an explicit completion signal. External SMB uploads
retain temporary-name/final-rename conventions plus stability checks.

Collect events while a pass runs; seal its work queue, then handle new events in
the next pass. Exclude protected state and recognize application-produced changes
using committed signatures/operation records. Do not ignore all `.photo.json`
changes, because external human overrides must be noticed. Scan newly watched
directories immediately to cover files that arrived before watch registration.

Startup, daily reconciliation, event overflow, remount, or detected inconsistency
requests a full inventory. Linux event queues can lose events; see the
[inotify documentation](https://man7.org/linux/man-pages/man7/inotify.7.html).
Force rescan is an explicit queued job with start/end times, progress and results.
A changed-file pass must still use library-wide duplicate candidates, folder
collision reservations, and source reverse dependencies. It cannot simply pass
only new uploads to the existing `ExactDuplicates` stage.

The current full runner is a valid first read-catalog bootstrap, but it is not a
per-request query implementation. Targeted jobs must preserve current safety
checks and processing checkpoints. Metadata-only input changes must not trigger
pixel analysis. Empty-directory cleanup uses affected ancestors for targeted
passes and respects the authoritative keep-empty registry.

## Deployment, recovery, and diagnostics

Validate library marker, expected volume identity/mount, writable capabilities,
free space, codecs, broker connectivity, and supported writer format at startup.
If storage disappears, stop media/metadata writes, retain jobs, mark unavailable,
and resume after identity checks. Never create directories at an unmounted fallback
path. Recovery precedes mutations. A damaged sidecar is reported and preserved.

Use systemd mount dependencies and resource/process isolation. The official
[systemd execution documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
describes directory dependencies and sandbox controls; choose options compatible
with the mounted volume and separate broker. Loopback API binding behind a TLS
proxy is the default. No public sharing is configured by this spec.

Expose liveness independently from readiness. Readiness reports missing storage,
initial catalog build, unsupported schema, or unavailable authentication. Existing
authorized sessions may browse cached metadata during a volume outage, with a
clear stale-data banner; original/thumbnail responses require available validated
storage identity. Do not treat missing media as deletion without reconciliation.

Report API latency, catalog rows/age/query time, filesystem port accesses/bytes,
scan reasons/duration/processed/changed counts, job queue wait, thumbnail metrics,
upload bytes/reservations, errors, and free/trash/cache space. Avoid user labels in
metric names. Logs use request/job IDs and redact credentials and tokens.

Back up originals, sidecars, library/folder/source-location intent, journals and
trash manifests together with configuration. Indexes/thumbnails/exports can be
rebuilt. Session loss logs users out. Document restore and test it on a scratch
library; migration rollback is allowed only before new-format mutations, otherwise
restore a consistent backup rather than downgrading markers in place.
