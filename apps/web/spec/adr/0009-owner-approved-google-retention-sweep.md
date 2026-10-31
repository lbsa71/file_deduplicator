# ADR 0009: Owner-approved Google retention sweep

Status: Policy implemented; production execution remains gated — 2026-10-31.

The owner requested a real production sweep that retains every Google photo that
is starred, belongs to any album, or is not available as a verified local original.
The owner states that an independent Takeout backup exists and explicitly waived
verification of that backup. This supersedes the independent-backup verification
requirement in ADRs 0003 and 0008 and the standalone retention policy/executor.
Do not report the owner assertion as verified evidence.

## Retention rule

Keep a Google item if any of these applies:

- It is starred/favorited remotely, or an existing local positive decision protects it.
- It belongs to any Google album, including shared albums, or is locally curated.
- A complete, exact local original is missing, ambiguous, stale, corrupt or unproved.
- Required account, identity, ownership, companion or source metadata facts are unknown.

Only an unprotected item with verified local bytes can become a reviewed Trash
candidate. A filename, thumbnail, Takeout URL, perceptual match or file size alone
does not establish local availability. Missing photo metadata does not establish
remote absence. Unsupported media and motion/companion uncertainty stay protected.

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

Production execution still needs a qualified evidence-bearing authority distinct
from the explicitly disposable pilot exception. A complete inventory and reviewed
manifest must precede the finite production run. Existing pilot jobs, journals and
failed preparations remain intact. No automatic full-account Trash is enabled by
this policy revision.

## Validation

Tests prove that accepting an unverified backup does not waive local-original
checks, that missing/unknown local evidence cannot authorize removal, and that a
remote-only item produces no automatic download or Trash operation. Manifest
policy and decisions are covered by their immutable SHA-256.
