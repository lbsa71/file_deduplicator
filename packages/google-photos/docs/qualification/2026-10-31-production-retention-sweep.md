# Production retention sweep preparation — 2026-10-31

The owner requested keeping every starred Google item, every member of any Google
album, and every item without a verified local original. The owner explicitly
asserted an existing Takeout backup and waived verification of that backup.
[ADR 0009](../../../../apps/web/spec/adr/0009-owner-approved-google-retention-sweep.md)
records that policy. Backup evidence is not falsely upgraded to verified.

## Inventory contract fix

The page-111 validation failure was traced to a colon-containing dedup key.
Companion and server now use a distinct bounded dedup-key contract: nonempty
letter/digit/underscore/hyphen segments separated by colons, up to 256 characters.
Media identifiers and photo URL rules are unchanged. Empty segments, percent
encoding, punctuation, whitespace, controls and oversized values remain rejected.
Account-bound local associations use the same contract; differing identities
remain distinct and cannot silently match.

## Policy and deployed state

Read-only manifests include the keep rules, policy version, owner-asserted Takeout
backup requirement and `backupVerified: false` within the reviewed canonical hash.
Remote-only items are explicitly kept, with no automatic download-then-Trash.
Candidate references remain blocked pending current content and identity evidence.
The backup waiver removes only the backup-verification gate.

Server code through `f46c647` was installed on the existing production host.
The existing companion installation was rebuilt/reloaded without clearing pairing
or journals. The served 0.4.0 ZIP was replaced with the matching build and inspected
to confirm both the dedup contract and owner-approved policy. Production health
returned HTTP 200 after the normal catalog rebuild. The restart invalidated the
web login; a fresh sign-in was requested before browser qualification resumes.

Tests: 141 package tests and 133 backend tests pass. The selected-policy synthetic
extension run completed 36 jobs, with immutable download, idempotent commit,
original import/deduplication and unknown-write reconciliation without replay;
all 141 Google requests were synthetic. Live inventory acceptance of the new
colon contract still requires the narrow page retry after sign-in.

## Next gates

1. Verify the former failed page read with both deployed contracts, then start one
   replacement read-only full inventory. Preserve old failed preparations.
2. Complete library, favorite, all album and member pagination before drawing
   conclusions about absence or unprotected status.
3. Assemble and qualify exact local-original/current-remote-byte evidence and a
   production authority path distinct from disposable qualification pilots.
4. Review a finite manifest and qualify a bounded production batch before the
   broader sweep. No automatic full-account Trash is enabled by this revision.

The image publisher is outside this cleanup-only scope. Unknown ownership,
companions, metadata, local bytes or remote membership remain holds. No permanent
deletion or production sweep has been executed. Real account values, identifiers,
private manifests and diagnostic artifacts remain outside Git.
