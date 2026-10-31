# ADR 0007: Cloud cleanup before publication, with observed quota gating

Status: Accepted — 2026-10-31.

## Decision

The owner requires Google Photos cleanup candidates to be processed before new
local images are uploaded, to make room within the Google account storage limit.
After inventory, preservation checks and plan review, cleanup is the first remote
mutation phase. Publication is a later phase with a separate capacity check.

```text
Inventory and identity/preservation verification
  -> freeze and review cleanup/publication plan
  -> execute eligible cloud cleanup and verify outcomes
  -> refresh quota; wait until sufficient headroom is observed
  -> publish selected new local images, verifying each outcome
  -> await and reconcile manually imported Takeout metadata
```

Downloading missing originals and collecting evidence are preflight/preservation
work, not publication. Existing retention rules still protect favorites, curated
album members, incomplete local originals/companions, missing Google metadata and
unknown identity/state. Do not delete additional protected items to meet a storage
target. An empty cleanup phase is valid; uploading may proceed if the other gates
pass and observed capacity is already sufficient.

## Trash is not proof of reclaimed storage

Google's account storage guidance states that trashed items count until permanently
cleared, and bulk cleanup can take 48–72 hours to be reflected in storage usage:
[Manage storage in Drive, Gmail and Photos](https://support.google.com/drive/answer/6374270?hl=en).

Some Photos originals do not consume quota; deleting those does not increase
available capacity. See [Google Photos storage guidance](https://support.google.com/photos/answer/9284827?co=GENIE.Platform%3DDesktop&hl=en).
Local byte size and successful trash acknowledgements are therefore not a quota
credit. Report estimated savings separately from actual observed free space.

The existing implementation permits reversible trash pilots and has no permanent
delete/empty-trash capability. This ordering decision does not introduce one.
If Trash has not released space, the run waits for provider expiry or a separate,
explicit operator action and subsequent quota refresh. Never empty the entire
account's Trash to unblock uploads: it may contain unrelated items. A future
targeted permanent-delete integration would require its own explicit authorization,
finite exact-target plan, preservation evidence, implementation and qualification.

## Coordinator contract

- Freeze cleanup targets and upload intents together, bound to account, current
  content/metadata revisions and retention reasons. Resolve conflicting actions
  before dispatch. The same proved content must not be both cleaned up and newly
  published by this run through different local/remote occurrences.
- Revalidate each cleanup target immediately before its write. Preserve the
  existing one-write-at-a-time journal, response and postcondition checks. Failed
  or uncertain cleanup blocks the dependent publication phase; reconcile or create
  a new reviewed plan rather than silently falling through to uploads.
- After cleanup completes, read account quota afresh. Uploads need verified
  headroom for their bounded batch plus a configured reserve. Missing, stale or
  insufficient capacity yields a durable `waiting-for-quota` state, not a failed
  upload loop. Reserve/batch accounting is prospective; do not assume deleting a
  file released its local byte size.
- Google storage is shared with other services and may change outside PhotoFlow.
  Recheck capacity before subsequent upload batches. If Google rejects a transfer
  after it was sent, retain its uncertain outcome under the upload ledger rather
  than blindly resending when capacity later improves.
- Persist phase, completed cleanup IDs, quota observation time/values and upload
  receipts. Browser sleep, process restart or a later scheduled pass resumes the
  gate without repeating verified cleanup or completed/uncertain uploads. Use
  bounded, delayed refreshes; do not keep an interactive worker waiting for days.
- Newly published images remain protected while awaiting matched Takeout metadata.
  They are not fed back into cleanup during this frozen run. Reevaluate them only
  in a later run using the normal retention policy and fresh evidence.

## Acceptance cases for the future reconciliation coordinator

1. With both cleanup and upload candidates, no upload is dispatched before eligible
   cleanup completes and quota is refreshed.
2. Successful trash with unchanged quota leaves the run waiting when capacity is
   insufficient; it sends no upload and no permanent-delete request.
3. If quota later becomes sufficient, resume uploads without repeating cleanup.
4. Cleanup failure/unknown outcome, unknown quota and account/revision changes
   prevent dependent uploads until resolved or replanned.
5. Zero cleanup candidates and sufficient observed capacity allow publication;
   zero candidates and insufficient capacity remain waiting with an explanation.
6. Items that do not consume quota never contribute assumed reclaimed bytes.
   No additional protected items are selected to make an upload batch fit.
7. Conflicting delete/upload intents for proved identical content are rejected or
   resolved by retention/publication policy before execution.
8. Restart during quota waiting, lost upload acknowledgements and repeated Takeout
   imports do not cause duplicate cleanup, repeated uploads or premature deletion.

This specifies the ordering for the reconciliation coordinator still to be built;
it does not claim the current independent worker jobs already enforce the phases.
