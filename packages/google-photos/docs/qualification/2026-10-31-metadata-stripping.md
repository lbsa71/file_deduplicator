# Metadata stripping reconciliation check — 2026-10-31

Two new standalone JPEG originals were downloaded through the paired extension
and direct server import into the scratch library. Nearby motion photos were
skipped. Byte-for-byte original and sidecar backups were saved outside the active
library before editing the test files. Private media and identifiers are excluded
from this report and committed fixtures.

| Check | Image 1 | Image 2 |
| --- | --- | --- |
| Original bytes | 3,353,370 | 501,338 |
| Embedded metadata tags before | 75 | 15 |
| Embedded metadata tags after | 0 | 0 |
| Stripped bytes | 3,329,063 | 485,088 |
| Decoded RGB dimensions/pixel hash | Unchanged | Unchanged |
| Baseline reconciliation review | verified-local | verified-local |
| Review after metadata stripping | local-content-changed | local-content-changed |
| Review after restoring originals and verification scan | verified-local | verified-local |

ExifTool 13.55 removed embedded metadata; EXIF/IPTC/XMP/ICC checks returned no
remaining tags. Local byte hashes changed despite identical decoded pixels.
Reconciliation correctly withheld original verification for both changed files and
added `local-original-unverified`; retention eligibility stayed false throughout.
The saved Google observations were reused without additional reads during local
refreshes. No cloud mutation was issued by this workflow.

The first run exposed a classification defect: a changed local file size was
reported as changed remote details before checking local bytes. The fix verifies
local SHA-256 first. Its regression test covers both an unchanged catalog and a
catalog already updated with the changed local hash/size. All 122 backend tests
pass after the fix.

The active originals were restored and independently rehashed against import
receipts. A normal library verification scan preserved record IDs and Google
associations while moving originals into canonical library paths. A final review
verified both local originals again. Stripped copies and complete before/after
reports remain in the private local test directory.

This qualifies changed-original detection and conservative review behavior.
Automatic metadata restoration, metadata-free identity recovery and cloud
retention execution remain outside this proof.
