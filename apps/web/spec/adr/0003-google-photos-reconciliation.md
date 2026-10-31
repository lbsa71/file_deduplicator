# ADR 0003: Google Photos retention and metadata round trips

Status: Library architecture accepted — 2026-10-30. The standalone package and
capture tooling are implemented in `packages/google-photos`. Live count reads
and initial read-only worker integration are implemented; further operations
remain pending. Production cloud
mutations are not enabled.

## Intent and retention requirements

PhotoFlow owns the complete local archive. Google Photos retains favorites,
explicitly curated album members, items not verified locally, and images whose
Google metadata has not yet been imported. Locally favoriting an image or adding
it to a curated album makes it a publication candidate. Images without Google
metadata should also be published so a later Takeout can enrich the local record.

Treat the retention reasons as an OR. Unknown identity or current remote state
protects an item from cleanup. Generated folders, saved searches, and integration
transport/review albums do not count as curated albums. Record album identities
and intent; do not decide this from a title alone. Protect live remote favorites
and curated membership as well as local positive decisions; clearing a local
flag must not silently erase an independent remote decision.

"Google metadata" means a valid Google source document unambiguously associated
with the relevant content revision and connected account, with export provenance.
EXIF, a generic sidecar, an upload receipt, or an unrelated Google JSON document
does not satisfy the metadata round trip. Legacy exports without proved account
attribution require reconciliation; never guess the account. Invalid/ambiguous
metadata is an error to resolve, not evidence of an absent remote photo.

The missing-metadata rule is temporary under its literal interpretation:

```text
No matched Google metadata
  -> establish remote presence; upload once only if absence is established
  -> verified remote presence, awaiting Takeout metadata
  -> import and verify matching Takeout metadata
  -> evaluate normal favorite/curated-album/local-presence rules
```

An ordinary unfavorited image outside curated albums may therefore become a
cloud-cleanup candidate after its metadata returns. Permanent retention based
on non-Google origin would be a separate policy, not an implied rule. An upload
does not guarantee Google will produce people labels or other particular
enrichment, nor does this proposal automate requesting/downloading Takeout.

Missing Takeout metadata does not imply missing remote content. Maintain upload
state independently, keyed by account and full local content hash, so subsequent
scans neither upload again while waiting nor reset the metadata wait on failure.
Identical local occurrences share publication evidence but preserve their source
provenance. Different encodings, edits, and Live Photo components remain distinct
until their relationship and completeness are proved. Unsupported media are
reported explicitly and preserved; do not silently transcode originals to make
an upload succeed.

## Upstream assessment

Inspected Google Photos Toolkit 3.3.0, commit
`6db9ab355e4797327e4078cf87a2b6994d36cf73`:

- [API client](https://github.com/xob0t/Google-Photos-Toolkit/blob/6db9ab355e4797327e4078cf87a2b6994d36cf73/src/api/api.ts)
  includes inventory, favorites, albums, item details, remote hash lookup,
  favorite changes, trash, and restore. No media-byte upload implementation was
  found in the inspected client. Its generic request loop retries mutations too.
- [Pagination and batch helpers](https://github.com/xob0t/Google-Photos-Toolkit/blob/6db9ab355e4797327e4078cf87a2b6994d36cf73/src/api/api-utils.ts)
  can return accumulated items after a page error; batch helpers log and skip
  null/non-array responses. This does not meet our completeness requirements.
- [Response parsing](https://github.com/xob0t/Google-Photos-Toolkit/blob/6db9ab355e4797327e4078cf87a2b6994d36cf73/src/api/parser.ts)
  uses optional positional fields and some empty/default fallbacks. A decoded
  object is not independently validated evidence that an item is unprotected.
- [Browser context](https://github.com/xob0t/Google-Photos-Toolkit/blob/6db9ab355e4797327e4078cf87a2b6994d36cf73/src/windowGlobalData.ts)
  depends on the signed-in Google Photos page and session values. This is not a
  ready-to-run server integration.
- [MIT license](https://github.com/xob0t/Google-Photos-Toolkit/blob/6db9ab355e4797327e4078cf87a2b6994d36cf73/LICENSE)
  allows adapting the necessary code with its copyright and license notice.

These are source findings, not proof that the undocumented calls currently work
for this account. The remote hash lookup needs qualification of its algorithm,
encoding, coverage, and no-match semantics. Its hash and Google's dedup/media keys
must not be assumed to be PhotoFlow SHA-256 values or interchangeable API IDs.

## Proposed architecture

Build a small PhotoFlow-owned adapter using pinned, attributed Toolkit protocol
knowledge. Reuse narrowly useful request formats and fixtures after reviewing
their provenance; replace permissive parsing, pagination, retries, and orchestration.
Do not take a runtime dependency on the whole auto-updating userscript or copy
its bulk workflow. Follow [CONTRIBUTING.md](../../../../CONTRIBUTING.md).

The first browser companion runs in an authenticated Google Photos page. It
performs validated reads and executes finite account-bound plans from PhotoFlow;
it does not own retention policy. Use explicit pairing, narrow permissions, and
authenticated message exchange; do not expose Google cookies/session tokens to
the PhotoFlow server or accept arbitrary RPC commands from web pages. Browser
availability is a requirement of this route; unattended scheduling would need
additional session management and qualification.

Provide uploading through a separate adapter. Prefer the documented
[Library API upload flow](https://developers.google.com/photos/library/guides/upload-media)
if the integration is eligible under the applicable API policy and OAuth is
configured. Otherwise an independently qualified browser upload path is needed;
Toolkit does not supply it. Validate each creation result, bind its remote ID to
the local revision, and qualify how official API IDs/product URLs map to browser
IDs. Do not assume an identifier conversion or insert machine bookkeeping into
Google's user-facing description field. The documented API uses original-quality
storage and has format/size limits; report unsupported items and quota failures.

Keep three separate persisted concepts:

1. Local desired retention/publication and its reasons.
2. Account-specific observations with provenance, observation time, and explicit
   completeness. Takeout is a dated snapshot; merged historical metadata is not
   the live account state. A partial export cannot prove absence.
3. Durable intents/results for upload, metadata wait, favorite/album operations,
   and cloud trash, including unknown outcomes. This ledger is authoritative,
   portable state; the query catalog is only a projection.

Local library or account changes invalidate plans. No remote mutation may use an
unproved filename/similarity match. A malformed/partial hash response cannot
authorize uploading; unknown remote presence stays unresolved. A positive hash
lookup is a candidate association until the remote identity/content guarantees
are qualified, with downloaded originals and full verification where necessary.
Never use a remote lookup miss alone to authorize cloud removal.

Cloud trash additionally requires the exact original and all required companion
media verified in the active local library, matched metadata preserved, a verified
independent backup, and freshly checked remote favorite/album/ownership state.
Shared or ambiguously owned items remain protected until their semantics are
explicitly supported. Local trash is not a verified active archive copy. Cloud
actions never delete local originals or metadata and never empty Google's trash.

Freeze explicit account/remote IDs and expected local revisions in each plan.
Recheck preconditions immediately before a mutation and read back its effect
before completion. Unknown outcomes block further writes and require
reconciliation, not blind retries. Start with one mutation in flight. Undocumented
Google calls provide no established atomic compare-and-swap for these facts;
there is still a race with concurrent Google edits and no promise that a bad
provider call cannot have a side effect before returning an error.

## Qualification and TDD gates

Current delivery: the standalone ESM package implements strict reads, pure
retention decisions, guarded favorite/trash/restore execution, durable Node
journals, documented API uploads, and passive Chrome/Edge/CDP capture tools.
Synthetic Chromium tests exercise the actual extension without real Google
traffic. Sanitized pinned upstream fixtures supplement behavioral tests. The
browser adapter supplied to users is read-only; no live mutation qualification
has been issued. See [package documentation](../../../../packages/google-photos/README.md)
for precise supported features, ports, installation, and remaining work.

1. Pure retention tests, including missing versus invalid metadata, incomplete
   export, changed revisions, generated versus curated albums, and unknown facts.
2. Strict raw-response fixtures: wrong RPC/account/IDs, shifted shapes, missing
   flags, empty/malformed bodies, pagination failure/loops, and HTTP success with
   semantic failure. Assert that no dependent mutation request was sent.
3. A read-only live inventory and identity-matching pilot on known originals,
   duplicates, edited/Storage Saver files, videos, and companion media. Resolve
   hash semantics and map identifier namespaces without guessing.
4. An isolated upload -> presence verification -> favorite/album changes ->
   Takeout import round trip. Test lost upload acknowledgements and restart so
   unknown outcomes cannot cause another upload. Verify actual metadata returned.
5. Reversible trash/restore on disposable media, including account switching,
   expiring sessions, partial responses, and concurrent metadata changes. Verify
   exact targets and that control media remain unaffected.
6. Only after these gates, expose real-library plans with counts, retention
   reasons, unresolved items, and explicit execution. The adapter remains
   replaceable and versioned; protocol changes disable dependent mutations until
   requalified. There is no enabled unattended cloud cleanup in this proposal.

Google documents that cloud deletion can affect devices with backup enabled:
[deletion behavior](https://support.google.com/photos/answer/6128858?hl=en).
Account/device behavior must be part of deployment qualification. Official API
capabilities and use constraints are separately described in
[API changes](https://developers.google.com/photos/support/updates) and
[API policy](https://developers.google.com/photos/support/api-policy).

## Desktop worker transport and scope clarification — 2026-10-31

The agreed next application architecture uses a paired desktop extension opening
an outbound authenticated WSS connection to PhotoFlow. Ubuntu persists jobs and
policy decisions; the extension executes allowlisted operations in its signed-in
Google Photos tab and returns results. Google credentials stay on the desktop.
Media bytes use authenticated HTTPS transfers. Reconnection must reconcile any
write whose outcome is unknown before permitting another attempt. This worker
transport is planned, not implemented by the capture extension.

Takeout creation/download automation is out of scope; imports remain manual.
Cloud uploading is restricted to images, with no video upload requirement.
Preserved Takeout `sources[].documents[].document.url` is the primary remote
reference for existing imports, subject to account/identity verification. Newly
uploaded images retain remote identity in receipts. Content matching remains a
fallback for missing or ambiguous references, rather than the default for all
Takeout records. Local videos and required companion preservation remain relevant
to archival safety even though video uploading is out of scope.

The initial read-only WSS worker is now implemented; see
[ADR 0004](0004-desktop-google-worker.md) for its job protocol, limits, diagnostics
and new-operation development procedure. Cloud mutations remain disabled.
