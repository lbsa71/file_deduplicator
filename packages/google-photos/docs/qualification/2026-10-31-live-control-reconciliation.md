# Live disposable-control reconciliation — 2026-10-31

Production endpoint: `https://photos.lbsa71.net`. Existing unpacked companion:
0.4.0, job protocol 2. Its installed source directory was verified in Chrome,
then rebuilt and reloaded in place. Pairing, storage and mutation journals were
preserved. The owner explicitly approved uploading the displayed synthetic
control, a reviewed Trash pilot on that control only, and restoration.

## Live Google evidence

- Uploaded one synthetic 640×360 JPEG through the ordinary Google Photos UI.
  Google confirmed its filename, original quality and 23,467-byte size. This is
  fixture setup, not qualification of PhotoFlow's real image publisher.
- Qualified album membership with this same control: added it to a newly created
  private test album, observed that membership, removed only the control, and
  observed an explicit null at extended-details field 19. The field was present
  in a 33-element row. Missing fields remain unknown. The empty private test
  album was kept; no album was permanently deleted.
- Google Trash initially showed “No items.” Its read RPC `zy0IHe` returned an
  empty array. A first commit stopped during preflight on that representation,
  before intent persistence or any write. The failed execution was preserved.
- After the tested empty-Trash fix, a fresh selected-only manifest prepared
  successfully. Its three executable operations were fresh photo-details, Trash
  of the exact control, and account quota. All 24,272 local publication candidates
  remained held.
- Downloaded the complete private manifest and verified its canonical SHA-256
  against the displayed reviewed hash. It was approximately 29 MB; downloading
  and local-revision checks were slow. Private manifests remain outside Git.
- The fresh commit succeeded: three completed operations, zero deferred, 24,272
  held. The worker reported Trash verified. Google Trash contained only the
  approved control, matching its exact library identifier and visible image.
- Repeating approval of the same manifest left the existing commit execution
  list unchanged and created no second Trash job. This supports the existing
  idempotent receipt behavior, also exercised by synthetic end-to-end tests.
- Restore first stopped during preflight because normal library details are
  unavailable while a photo is trashed. No restore write was sent in that attempt.
  After the tested restore fix, a new exact-target restore job succeeded and
  reported a verified outcome. Google Photos displayed the same control back in
  the library, with its filename, dimensions and original-quality backup. A fresh
  Google Trash page again showed “No items.”

No permanent deletion, unrelated-photo write, automatic publication or full
retention run was performed. The uploaded disposable control remains restored.

## Fixes and verification

Extended details normalize an explicit null album field to an empty membership
list under the controlled contract; omitted fields remain unknown. Only the
qualified Trash RPC/page accepts an empty payload as a complete empty inventory.
Other empty read payloads still fail closed.

Restore binds the current complete Trash inventory to both journaled media and
dedup identifiers. Incomplete, ambiguous or mismatched entries stop before a
write. Restoration requires both absence from Trash and a fresh exact-identity
library read; absence alone cannot verify success. A failed postcondition becomes
an unknown outcome and prevents replay.

Identifier-failure diagnostics add only fixed punctuation booleans. They export
no rejected key values. The full-inventory mismatch is documented separately in
[the preparation validation note](2026-10-31-production-preparation-validation.md).

Strict TDD reproduced the album, empty-Trash and restore failures before their
fixes. All 138 package tests pass. The final synthetic selected-policy extension
test completed 36 jobs, including manifest byte-preserving download, idempotent
commit, original import/deduplication and lost-write reconciliation without replay.
Its 141 Google requests were all synthetic. These results are separate from the
live Google observations above.

## Remaining production gates

Whole-library preparation remains partial at page 111: a colon-containing dedup
key is rejected by the companion's and server's generic identifier contracts.
Both need a reviewed, distinct dedup-key contract before completing inventory.
No full-inventory completeness or remote absence is established by this pilot.

Arbitrary-image publishing, metadata round-trip evidence, independent backup and
production retention evidence remain held. The pilot qualifies the finite
prepare/commit/Trash/restore loop; it does not qualify a full synchronization run.

Real account values, photo identifiers, manifests, screenshots and diagnostic
captures remain local and are excluded from committed evidence.
