# ADR 0009: Owner-approved Google retention sweep

Status: Owner-authorized executable Takeout sweep — 2026-10-31.

The owner requested a real production sweep that retains every Google photo that
is starred, belongs to any album, or is not available as a verified local original.
The owner states that an independent Takeout backup exists and explicitly waived
verification of that backup. This supersedes the independent-backup verification
requirement in ADRs 0003 and 0008 and the standalone retention policy/executor.
Do not report the owner assertion as verified evidence.

The owner subsequently clarified that downloads will come from periodic manual
Takeout exports. Automatic original downloading is optional and is not the focus
of this production sweep. Validate existing local Takeout bytes and provenance;
keep fresh Google protection/identity checks distinct, and never claim current
remote byte equality from a Takeout association alone.

## Retention rule

Keep a Google item if any of these applies:

- It is starred/favorited remotely, or an existing local positive decision protects it.
- It belongs to any Google album, including shared albums, or is locally curated.
- A complete, exact local original is missing, ambiguous, stale, corrupt or unproved.
- Required account, identity, star, album or local source evidence is unknown.
- A positive motion/companion marker lacks paired local proof.

Only an unprotected item with verified local bytes can become a reviewed Trash
candidate. A filename, thumbnail, Takeout URL, perceptual match or file size alone
does not establish local availability. Missing photo metadata does not establish
remote absence. Known motion photos stay protected. The owner accepts the preserved Takeout original for items without a positive companion marker; a missing marker is recorded as unknown, never relabeled as a verified negative.

Remote-only photos remain in Google. Do not download them and then treat that new
copy as permission to remove the Google original during the same sweep.

The backup policy is `owner-asserted-takeout`, with `backupVerified: false`.
Manifests include this policy and its keep rules inside their canonical hash.
The assertion removes only the backup-verification gate; it does not supply any
missing local-byte or remote-identity evidence.

## Execution boundary

This is a cleanup sweep, with no upload or permanent-delete requirement. The
unconfigured image publisher does not need to be implemented to finish this scope.
Complete library, favorites and all album/member inventories are required before
classifying candidates. Recheck exact targets, stars and membership immediately
before writes; stop on incomplete reads, changed identities or unknown outcomes.

The owner explicitly instructed: “Change the policy and make the sweep actually
trasha and run it.” This authorizes execution of this finite, reviewed production
sweep without a second approval request. It supersedes the prior report-only gate
and the requirement to compare freshly downloaded Google bytes. Periodic manual
Takeouts remain the owner's preservation workflow.

`google.prepare-takeout` derives a new immutable executable manifest from the
complete account inventory. Every target must have one unambiguous local SHA-256,
current verified local bytes, an unchanged sidecar, an exact Google URL and matching
original filename/title in a preserved, hash-verified Takeout document. Missing
copies, ambiguous matches, protected items and positive motion markers stay kept.
The owner accepts this evidence as local-original availability, without asserting
current Google byte equality or verified independent backup.

Commit issues a distinct `owner-authorized-takeout-retention` capability, never a
fake disposable pilot scope. It binds account, job, exact media/dedup identities,
local SHA-256 and reviewed manifest hash. One target is in flight. Local evidence
is rechecked before enqueue; the extension rechecks current identity, known star
state and explicit empty albums before writing. Newly protected targets produce
kept receipts. Intent is journaled before sending. Positive exact membership in
Trash is required before proceeding; unknown outcomes stop the run and cannot be
automatically retried. No download, upload, album mutation or permanent delete is
part of this sweep. Existing pilot receipts and journals remain intact.

## Validation

Tests prove that accepting an unverified backup does not waive local-original
checks, that missing/unknown local evidence cannot authorize removal, and that a
remote-only item produces no automatic download or Trash operation. Manifest
policy and decisions are covered by their immutable SHA-256.
