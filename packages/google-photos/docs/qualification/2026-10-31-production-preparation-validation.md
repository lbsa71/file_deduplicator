# Production preparation validation stop — 2026-10-31

Implementation inspected: `beb9577`; companion owner-confirmed at 0.4.0, job
protocol 2. The existing production pairing was reused without clearing storage,
re-pairing, or starting a duplicate full preparation.

## Live evidence

The existing whole-library preparation advanced through library page 110 and
stopped on `library-page::111`. The preparation state is `partial`. Server job
diagnostics show one attempt with phases `checking`, `reading`, `verifying`, then
`failed`, and controlled error code `INPUT`. The RPC result reached worker result
verification; the diagnostics currently do not identify the rejected field. This
does not qualify full-account completeness or prove remote absence.

The full-library preparation has not authorized any Google mutation. Completed
read steps and failed jobs remain preserved; no journal or queue was cleared.
A separate owner-approved disposable-control pilot is recorded in the
[live control qualification](2026-10-31-live-control-reconciliation.md).

The synthetic JPEG upload has now succeeded. Chrome's file-URL setting was
already enabled; refreshing the disconnected controller session restored file
selection. No personal photo was substituted for the approved control.

A narrow retry of the last complete page's continuation reproduced the validation
failure. The updated installed worker's value-free diagnostics identify
`dedupKey`, string length 39, with a colon, and no whitespace, control characters,
non-ASCII characters, slash, plus or padding. The generic typed `id` rule accepts
only letters, digits, underscore and hyphen, while the protocol adapter's opaque
identifier parser accepts this value. This is a contract mismatch, not a login
failure. The mirrored server contract also uses the generic `id` rule. Neither
acceptance rule has been loosened; full enumeration remains incomplete pending a
reviewed distinct dedup-key contract in both implementations.

## Diagnostic improvement

Rejected typed result identifiers now annotate errors with field name, expected
type, value type, bounded string length and fixed character-class booleans (including punctuation). Worker
diagnostics accept only these allowlisted fields. They do not include the rejected
value, arbitrary error text or arbitrary error properties. Validation rules and
their rejection behavior are unchanged.

Regression tests cover rejected media/dedup identifiers, oversized identifiers,
character-class reporting and private-value redaction. All 138 package tests pass
after the controlled-response and restore fixes.
The local backend suite passed 130 tests. The updated diagnostic build's synthetic
selected-policy extension flow completed 36 jobs including prepare, manifest
download and idempotent commit. Synthetic outcomes are not live evidence.

## Next qualification steps

1. Define and test the distinct opaque dedup-key contract in both the companion
   and server before updating production. Preserve exact media-key URL rules.
2. Reattempt whole-account preparation only after that contract mismatch is
   resolved. Preserve publisher, metadata-round-trip and production-retention
   proof holds.
3. Keep live disposable-control mutation qualification separate from synthetic
   end-to-end results and full-account inventory completeness.

Real identifiers, account values, private diagnostics, manifests and screenshots
remain local and are excluded from this note and committed fixtures.
