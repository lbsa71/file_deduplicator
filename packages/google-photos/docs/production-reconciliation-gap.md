# Gap assessment: production Google Photos reconciliation PoC

Assessment date: 2026-10-31. Repository reviewed at `afbd21a`, after fast-forwarding
main from `8a7680c`. This is an assessment, not authorization to execute a new cloud
cleanup plan. No deployment or live Google mutation was performed for this audit.

## Implementation update

ADR 0008 now implements durable preparation, immutable inspectable manifests and
hash-bound sequential commit, plus selected-original verification/import and
explicit non-vital Trash pilots. It accounts for all inventory and local records
conservatively; unproved production retention and publication remain held. Quota
full/over-limit results defer publication to a later run, without active waiting.
The assessment below describes the original baseline and the remaining full-loop
gaps; this update does not claim a qualified live uploader or automatic retention.

## Conclusion and definition of done

The other session completed a valuable read-side vertical slice: live download of
one original, byte verification, transactional ingestion, duplicate suppression,
account-bound local verification and rendering. The individual worker operations
and transport are reusable. The application does not yet assemble them into an
end-to-end reconciliation run implementing ADR 0003's retention/publication rules.

A full-loop PoC should use the production Ubuntu service and paired desktop, make
a complete read-only plan against the real library/account, and execute a bounded
selected-image cohort through all applicable decisions: keep favorites/curated
albums, preserve/download cloud-only content, publish a local-only image once,
wait for manually imported Takeout metadata, then review and demonstrate reversible
cloud trash/restore for a fully eligible control. Restart and repeat the run; it
must converge without extra uploads, originals or unexplained writes. Every input
must be accounted for as acted on, retained, deferred, unsupported or unresolved.

This does not require completing every web-gallery acceptance gate or uploading
videos. It does require explicit protection/reporting for media outside the PoC's
supported image envelope. A supported-image PoC is not proof of whole-archive
destructive reconciliation.

## Evidence checked

- Latest source: 23 typed worker operations, including `download-original`.
- Live qualification report: `qualification/2026-10-31-single-original.md` records
  a 301,586-byte original imported through the local Mac development server and
  a second download resolving to the same local record/hash. No cloud mutations
  were qualified by that work. The local association check proves saved local
  bytes, not current remote byte equality or retention eligibility.
- Fresh Linux verification: 130 Google package tests, 109 web tests (2 platform
  skips), 120 core tests and 24 UI tests completed without failures. Contract mirror
  check and frontend/extension builds passed.
- Fresh actual-extension HTTPS/WSS synthetic test under selected-target policy:
  30 successful jobs / 23 operation types / 128 intercepted Google requests.
  It covers page pairing, endpoint preservation on pairing failure, original
  import/reuse, local association checking and uncertain-write reconciliation
  without replay. No real Google requests were sent by this test.
- Production public health returned 200. Installed Ubuntu backend still exposes
  only 22 operations and lacks `download-original`. The served 0.3.1 ZIP also lacks
  that operation and the new page-pairing script. Source and published manifest
  versions both say 0.3.1 despite their different capabilities/permissions.
- Production Google job state: one paired worker; one successful inventory-counts
  job; no recorded production mutation jobs. No pilot account allowlist configured.
- Read-only production catalog aggregates: 24,283 media records; 20,043 records
  containing a preserved Takeout photo URL; zero records with a `google_originals`
  verified-download association. These are record counts, not unique remote items.
- Local formats: 15,157 JPG, 86 JPEG, 371 PNG, 6,019 HEIC, 15 GIF, 3 DNG and
  2,632 video files across MP4/MOV/3GP/AVI/M4V. 15,614 records fall within the current
  importer's JPEG/PNG/WebP + 16 MiB format/size envelope; this does not prove they
  are standalone originals without companions. 541 records exceed 16 MiB overall.

Only aggregate production observations are retained here; no private account,
media identifiers, URLs or content hashes are included.

## Blocking gaps

Execution order is governed by ADR 0007: preflight and a frozen plan, verified
cleanup of eligible existing cloud items, observed quota headroom, then new local
publication. Successful trash does not imply reclaimed storage. A persistent
quota gate is required while automatic permanent deletion remains absent. Existing
headroom is immediately usable; insufficient capacity defers uploads to another run.

| Area | What exists | What a production reconciliation PoC still needs |
| --- | --- | --- |
| Coherent production release | Local development endpoint/pairing, tested source, healthy older Ubuntu deployment | Publish a distinct extension release and matching server build/capability set; preserve pairing/journals. Verify download from Ubuntu's network, not just the Mac's network, then configure the exact authorized account for selected pilots. |
| Complete remote observations | Complete count enumeration and bounded page/detail jobs | A persisted run inventory: all library items, favorites, albums and required album memberships, cursors, timestamps, account and completeness evidence. Counts and a terminal page cannot substitute for the inventory. Resume without losing progress when the browser sleeps. |
| Existing-library identity and metadata evidence | Saved Takeout URLs and new `google_originals` index for verified imports | Bootstrap account attribution and verified identity/content associations for existing Takeout-backed records, duplicates and variants. Legacy URLs are deliberately not indexed as verified mappings. Prove ambiguous/no-match cases instead of treating unmapped as absent. |
| Facts, desired state and plan | Pure `decideRetention(facts)` and guarded library `MutationExecutor` | Wire authoritative facts into policy, persist the reasoned plan, distinguish curated album IDs from generated folders/transport albums, and map local positive favorites/album intent without erasing independent remote choices. Add review/execution UI or an inspectable CLI/API. |
| Image publication and metadata round trip | Standalone tested `OfficialUploader` and durable upload journal primitives | A usable image-upload worker/transfer/auth adapter. Browser pairing supplies no OAuth token for `OfficialUploader`. Qualify presence/absence and content matching so missing metadata cannot cause duplicate uploads. Persist account+SHA upload/awaiting-metadata state and close it only after a validated manual Takeout import. |
| Production mutation execution | Explicit Toolkit pilot writes with account/target checks, browser journal and read-back; stricter standalone retention executor | Qualify live favorite/album/trash/restore operations under ADR 0006, then connect the stricter production executor to freshly verified ownership, current favorite/membership, original/companion, metadata and backup facts. Pilot permission is not evidence that a policy-generated trash decision is valid. |
| Durable run orchestration and scale | Durable Google job queue; new tested local JobStore/JobCoordinator; recoverable file transactions | Wire a reconciliation coordinator and run/step ledger into the app. Current local jobs still use an in-process ThreadPoolExecutor; the new coordinator is unwired. Tie remote receipts, local commits, plan revisions, cancellation and unknown outcomes together. Add bounded concurrency, backpressure and indexed candidate lookup. |
| Transfer coverage and preservation | One anonymous direct server fetch, single-member ZIP, JPEG/PNG/WebP <=16 MiB, hash verification and reuse | For archive-wide coverage: larger images, HEIC/other formats, motion/Live Photo companions, multi-member archives and archival video download where needed. Keep unsupported or unknown companion cases protected. Browser-byte relay remains absent if anonymous Ubuntu fetching is unavailable. |

### Important details behind these gaps

`LocalGoogleMatches` explicitly returns `remoteBytesEqual: null`,
`absenceProven: false`, and `retentionReady: false`. It indexes only account-bound
`google_originals`, not the existing imported Google JSON source documents. A
verified mapping at download time cannot silently become permanent proof of
current Google bytes or fresh metadata state.

The existing metadata resolver aggregates album titles and defaults the displayed
favorite to false. A reconciliation facts builder must not interpret an unknown
remote flag as false, or every source folder/Takeout year album as curated
membership. Keep local intent, dated source documents and live observations
separate and preserve independent remote decisions.

`decideRetention` is not invoked by the app or worker: it returns reasoned decisions
when supplied trustworthy facts. Likewise, the production `MutationExecutor` is
not the browser pilot handler. It requires proved ownership and preservation
preconditions that the current detail DTO does not fully supply. Do not bypass
this gap by dispatching a policy-generated trash job through the looser pilot path.

The reported Takeout backup and the owner's personal-account pilot authorization
remain accepted under ADR 0006. Production policy still has a separate
`backupVerified` fact. Capture its evidence explicitly; do not silently equate a
backup claim or a second directory on the same disk with an independently verified
copy. Unknown evidence means retain/review, not an implicit exception to policy.

The original importer fetches/hashes across jobs, scans the filesystem for content
matches and deliberately handles only one item per job. That is reasonable for
the current slice. Calling it independently for an entire account would multiply
directory walks and hashes. The new identity index is useful for verified mapped
lookups; bulk matching also needs a bounded content/candidate index and validation
of cached file revisions. The current match verifier has a 256 MiB per-request
hashing budget and a maximum of 100 targets, which a run coordinator must respect.

## Recommended critical path

1. **Release parity and one production transfer.** Rebuild/release the extension
   with a new version, deploy matching Ubuntu code and confirm the existing pairing
   works. Perform the previously proven one-original import/reuse from the desktop
   through Ubuntu, including interrupted completion. Record actual cross-network
   evidence and the exact capability set. No broad cloud writes are needed.
2. **Read-only real-library reconciliation.** Implement a durable run inventory,
   legacy Takeout association bootstrap, observation/facts builder and policy plan.
   Produce counts and per-item reasons for keep, download, upload, await-metadata,
   review-trash, unknown and unsupported. A second unchanged run should reuse
   valid evidence; demonstrate stale plans and account changes are rejected.
3. **Close image publication.** Implement and qualify one actual upload path and
   its identity receipt, hash/presence semantics, unknown-acknowledgement recovery
   and awaiting-Takeout ledger. Perform a manual small Takeout round trip. Reimport
   it twice; it should enrich the same local record and never trigger another
   upload just because the original metadata was missing.
4. **Bounded full-loop production proof.** Use selected controls for a favorite,
   curated-album member, cloud-only original, local-only publication, waiting or
   ambiguous metadata, duplicate occurrence and fully eligible cleanup candidate.
   Review the frozen plan and execute eligible existing cleanup first, one mutation
   at a time. Demonstrate trash/restore qualification separately from quota release;
   refresh capacity before publication and record deferrals for another run if it is insufficient.
   Verify outcomes and untouched controls, interrupt/restart and rerun to
   convergence. Retain unsupported/unknown cases with explicit reasons.
5. **Expand coverage and volume.** Add larger/HEIC/companion handling and needed
   archival video support, measure a whole-account dry run and verify recovery and
   backup evidence before broadening mutation batches. Image uploading remains the
   agreed requirement; video uploading and Takeout automation remain out of scope.

The next implementation slice should be the durable read-only reconciliation
coordinator/facts/plan, following release parity. More unrelated gallery features
are not prerequisites for that slice. Publication and live mutation qualification
are essential before calling the full-loop proof complete.
