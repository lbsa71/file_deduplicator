# ADR 0008: Prepare immutable reconciliation manifests, then commit

Status: Implemented first vertical slice — 2026-10-31.

The owner-approved retention and backup-policy revision in
[ADR 0009](0009-owner-approved-google-retention-sweep.md) supersedes the independent
backup verification requirement below. Local originals and current remote state
still require verification; production execution remains gated.

## Contract

The owner requested a read-only preparation stage producing an inspectable manifest
of sequential operations, followed by a separate explicit commit stage. The owner
also authorized destructive qualification on explicitly selected non-vital images.
That is not authorization to treat arbitrary personal photos as disposable or to
bypass production retention evidence.

Whole-account preparation reads complete library/favorites/albums/member pages
through the paired browser worker. Explicit selections use bounded exact-target
details plus favorite/album observations; their manifest says `inventoryScope:
selected`, and does not claim whole-account completeness or remote absence. It persists read receipts, accounts for local active records and
Takeout candidate references, and writes a private JSON manifest. It does not
mutate Google content or managed originals/sidecars. Preparation may pause for the
browser and resume from durable read steps after restart. Repeated cursors and IDs,
partial pages, wrong account, invalid results and stale local records stop the run.

A manifest contains:

- Schema version, stable ID, owner, library ID, exact Google account and expiry.
- Options, counts, proposed decisions/reasons, held/unsupported items, and explicit
  implementation capability limits.
- Local record revisions, content hashes, paths and observed file fingerprints;
  Takeout references remain candidates until byte/account evidence establishes more.
- Read-step result digests and stable worker request keys for investigation.
- A numbered operation sequence with phase, operation, exact inputs and any extra
  preconditions or explicit non-vital qualification authority.
- SHA-256 of canonical JSON excluding the digest field itself.

The reviewed file is immutable. Commit identifies its ID and expected SHA-256;
server-side corruption, edits, expiry, storage/library/account changes or stale
starting revisions reject execution. To change targets or operations, prepare a
new manifest rather than submitting arbitrary edited RPC calls.

Commit persists its own execution command and per-step results independently of
the immutable plan. It runs preservation work first, then cleanup, then quota,
then qualified publication. Each remote intent has a stable request key that
continues to reference the same worker job after completion or restart. Queued
manifest jobs also have a deadline enforced at worker dispatch, and write grants
cannot outlive that deadline. A lost acknowledgement must not become a new write.

A repeated commit returns the original execution receipt. Interrupted commits may
be explicitly resumed after resolving their cause. Unknown Google outcomes stop
execution and require the existing read-only reconciliation path before resuming.
Worker jobs, manifests and operation receipts remain private to the owning admin.

Read-only preparations may also be explicitly resumed after diagnosing a stopped
read. Completed pages are reused; unfinished reads receive attempt-scoped request
keys. Failed worker jobs remain preserved, and the final manifest records the
actual successful request key for each observation. This never changes commit
intent keys or retries a cloud mutation. Account changes, unavailable storage and
expired preparations reject resume.

## Quota clarification

As the owner clarified, we do not wait for cleanup to release space if sufficient
space already exists. A fresh capacity read is used immediately. Full/over-quota
accounts produce explicit deferred upload outcomes and the run ends. A later
preparation run can evaluate those pending items using new observations. There is
no automatic quota polling loop or delayed upload retry for a completed run.
Browser availability is a different dependency and may keep a pending read/commit
queued. See ADR 0007 for cleanup-first ordering, reserve accounting and the lack of
an automatic permanent-delete/empty-trash capability.

## Implemented capabilities and explicit limits

The coordinator and authenticated API/UI are wired into the running application,
using the tested durable JobStore/JobCoordinator. Existing unrelated scan/export
jobs still use their legacy executor; this does not claim their migration is done.

Full-inventory preparation provides a conservative classification and reports
unproved legacy associations as held. Selecting a supported unprotected photo can
prepare a `download-original` preservation/verification operation, including for
an existing Takeout candidate. Commit uses the qualified importer's full download,
SHA-256 and duplicate reuse logic to establish an account-bound association. It
can safely preserve a different encoding as another original instead of assuming
that a reference proves identical bytes. A later manifest can reconsider evidence.

An explicit selected non-vital pilot can prepare a `photo-details` precondition
read followed by exact-target Trash. Live favorites/album membership and local
positive decisions remain protected. Known motion-photo targets are excluded;
unknown companion state is not converted to production preservation proof. The
selected non-vital exception is qualification authority for an expendable asset,
not a production-retention decision. Normal production cleanup remains held
because ownership, fresh remote content, source metadata and independent backup
facts are not yet fully assembled/qualified by this slice.

Publication is an injected, qualified port with inspect, publish and receipt
recovery contracts. Tests exercise its scheduling, headroom/reserve decisions,
receipt validation and unknown-outcome behavior using synthetic ports. The deployed
application has NO qualified publisher configured. Arbitrary-image upload candidates
therefore remain held; this slice does not claim a real upload integration exists.
The library's standalone OfficialUploader and OAuth transport still need an actual
worker/authentication/transfer adapter and live qualification. The full production
round trip remains incomplete until publication, metadata-wait integration and
production retention proof are connected.

## API and UI

All endpoints require the owning PhotoFlow administrator. Writes require the
existing same-origin/CSRF checks. Manifest responses are no-store and contain
private photo/account identifiers; do not commit real manifests to Git.

- `POST /api/v1/google/reconciliation/prepare` with optional `photoUrls` (up to 100;
  empty means full inventory), `nonVital` (default false; true requires explicit
  targets) and `reserveBytes` (default 256 MiB). Returns a durable command, HTTP 202.
- `GET /api/v1/google/reconciliation` lists the owner's commands.
- `GET /api/v1/google/reconciliation/jobs/{id}` returns progress/result/error.
- `GET /api/v1/google/reconciliation/manifests/{id}` returns the full private plan.
- `GET /api/v1/google/reconciliation/manifests/{id}/download` downloads the exact
  immutable JSON bytes, preserving large nanosecond timestamps through browser
  download instead of rounding them during JavaScript reserialization.
- `POST /api/v1/google/reconciliation/manifests/{id}/commit` with `sha256` schedules
  only that reviewed plan, HTTP 202. Non-vital pilots require the account's selected
  target policy from ADR 0006.
- `POST /api/v1/google/reconciliation/jobs/{id}/resume` resumes a stopped read-only
  preparation or an interrupted commit after validation. Capacity deferrals require
  a new run instead.

The Google connection panel includes Prepare and commit reconciliation, a private
manifest download and an explicit review/commit action. It shows operation order,
counts, limitations, receipts and deferrals. Download the complete manifest when
more than the first 100 operations are shown.

## Validation

Behavioral tests cover read-only preparation, complete enumeration, private/hash-
bound review, stale revisions/account/expiry, exact-target non-vital cleanup,
cleanup-before-publication, existing capacity, full and over-quota deferrals,
conflicting cleanup/upload content, duplicate commit receipts and crash recovery
without reissuing completed writes. HTTP tests cover admin authentication, CSRF,
owner isolation and review hashes. The actual-extension synthetic HTTPS/WSS test
prepares and inspects a manifest and commits its ordered operations, checking that
preparation sends no mutation and commit touches only its selected fixture.

All automated Google interactions are synthetic. Live operation qualification and
full-library production results must be recorded separately.
