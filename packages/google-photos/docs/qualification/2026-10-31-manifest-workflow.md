# Reconciliation preparation/commit verification — 2026-10-31

Release: companion 0.4.0, protocol 2, 23 typed Google operations. ADR 0008 describes
its preparation/commit contract and explicitly limited production capabilities.

## Synthetic evidence

Fresh verification on Ubuntu completed 130 web tests (2 platform skips), 131 Google
package tests and 24 UI tests without failures. The actual Chromium extension,
local HTTPS/WSS server and web UI completed 36 Google jobs across all 23 operation
types and 140 intercepted Google requests under selected-target policy.

The browser scenario verified:

- Desktop/page pairing, endpoint preservation after a failed pairing, WSS jobs,
  validated results and sanitized diagnostics.
- Original import/reuse and an account-bound local association check.
- Lost-write acknowledgement reconciled by reads without replay.
- Read-only preparation of a selected non-vital fixture manifest: no mutation was
  sent until separate review/commit.
- Exact-byte private manifest download, including original numeric timestamps.
- Hash-bound commit with fresh precondition read, exact-target Trash and subsequent
  quota read; the intended fixture changed and unrelated controls remained intact.

Unit/HTTP cases additionally cover complete/looping inventory, stale account/local
revisions, owner/CSRF checks, modified/expired manifests, dispatch deadlines,
request-key recovery, and read-only re-pairing recovery without reviving writes.
Selected preparations are explicitly scoped; they do not claim whole-account
absence proof. Local summaries stream from the catalog rather than duplicating
all portable sidecar bodies in memory.

A synthetic qualified publication port exercised cleanup-first ordering, immediate
use of existing capacity, reserve accounting, full and over-quota deferrals to a
later run, and conflicting cleanup/publication content. The deployed app does not
have a qualified real publisher. These tests do not qualify live Google uploads.

## Deployment and live status

Both current core/web packages were installed on Ubuntu, and the expanded server
and 0.4.0 companion are deployed at photos.lbsa71.net. Public health returned 200;
the companion ZIP returned 200 and matched the prepared artifact byte-for-byte;
unauthenticated access to the new reconciliation API returned 401.

The exact already-paired account is allowlisted for selected non-vital pilots, under
the owner's existing authorization. A whole-library read-only preparation was
queued and was waiting for the offline desktop worker at the latest check. It has
not produced a completed production manifest yet. No production Google mutation
was submitted by this verification. Live destructive qualification awaits the
connected desktop and an explicitly identified non-vital image; do not report the
synthetic test as live qualification.

Unproved production retention candidates and arbitrary-image publication remain
held in manifests. Manual Takeout enrichment and a real uploader, metadata-wait
ledger and full production preservation facts are still needed for the complete
reconciliation round trip. Permanent deletion/emptying Trash is not implemented.
