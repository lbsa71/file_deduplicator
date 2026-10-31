# Single-original download qualification — 2026-10-31

The existing Chrome extension was paired with the local development PhotoFlow
server. `library-page` and `photo-details` supplied a bounded selection; one
standalone image not already in the empty scratch library was imported by
`download-original`. No Google content or metadata was changed.

The extension obtained a temporary download reference. The server fetched it over
verified HTTPS without Google cookies or authorization, and Google returned a ZIP.
The accepted archive contained exactly one expected original. Its name and
uncompressed size matched Google details; image format and full SHA-256 were
verified before the local transaction. The imported original was 301,586 bytes.
No private identifiers, signed URLs, filenames, hashes or photo content are included
in this report or committed fixtures.

A second job for the same selected image fetched and hashed its bytes again. It
reported `already-present` with the same local record ID and SHA-256. Filesystem
and catalog inspection confirmed exactly one local record, unchanged original
bytes, and one Google identity mapping. Same-job transfer replay also verifies the
local original before returning its persisted receipt.

An earlier candidate was a motion photo. Its metadata declared a companion and
its archive contained two members. No import occurred. Known companions are now
rejected before requesting the download URL; multi-member archives remain rejected.

Validation includes 124 JavaScript package tests, 25 focused Google backend tests,
and the real-extension synthetic E2E test: 30 completed jobs across 23 operation
types, including direct single-member-ZIP import and duplicate suppression. The
transfer tests cover stale leases, wrong account/target, credential revocation,
unsafe hosts, redirects, length mismatch, HTML, wrong archive names and multiple
members. Synthetic E2E makes no real Google requests.

Limits: JPEG/PNG/WebP, 16 MiB, one original per job. There is no browser-byte relay,
companion handling, video download, bulk synchronization, automatic retry, or cloud
mutation qualification. Failure after local commit is reconciled through the
transactional receipt or a subsequent full-content duplicate check.

## Account-bound local verification

The local app's **Check local original** control verified the previously imported
image against its account-bound sidecar association and full SHA-256. The result
linked to the existing local record. This check downloaded no additional photo and
queued no Google operation. It proves the saved association and local bytes at
verification time; current remote byte equality and retention eligibility remain
unknown.

The synthetic extension flow now checks this control after its import and duplicate
jobs, verifies the local record link, changes the selected target, and confirms an
unmapped result without adding to the 30 Google jobs. Backend cases cover wrong
account and namespace, CSRF and role checks, changed bytes, stale sidecars,
trash/restore, catalog loss/rebuild, conflicting associations, one valid copy among
changed copies, verification budgets, and storage identity changing during a check.
