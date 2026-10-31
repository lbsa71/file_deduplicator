# Google Photos integration library

A standalone ESM package with no runtime dependencies or PhotoFlow imports.
Its directory can be moved into another repository without changing imports.
Node 18+ runs the core; development/browser tooling requires Node 20+ (22 recommended).

This release implements strict read adapters, a guarded mutation executor,
documented API uploading, retention decisions, durable journals, and passive
capture tools. It is tested against synthetic browser interactions and sanitized
Toolkit fixtures. **No live Google account has been qualified and no production
cloud cleanup is enabled.** The supplied browser transport is deliberately
read-only until the mutation protocol has been qualified with disposable media.

## Install and test

```sh
cd packages/google-photos
npm ci
npm test
npx playwright install chromium
npm run build:capture
npm run test:browser
npm pack
```

The browser test loads the actual extension in Chromium and intercepts every
Google Photos request with a disposable fixture. It checks read-only inspection,
sanitization, a capture downloaded through the popup, and that five observed
requests produce exactly five network calls. A separate oversized-response probe
must remain incomplete without replaying its request.
There is no dependency on a signed-in account for these tests. Playwright is a
pinned development dependency, not a runtime dependency.

Use a local path dependency during monorepo development:

```json
{
  "dependencies": {
    "@photoflow/google-photos": "file:../../packages/google-photos"
  }
}
```

## Read client

```js
import { GooglePhotosClient } from "@photoflow/google-photos";
import {
  createPageTransport,
  pageRequest,
} from "@photoflow/google-photos/browser";

// `page` is a Playwright Page already signed in at photos.google.com.
const identity = await page.evaluate(pageRequest, { operation: "identity" });
const client = new GooglePhotosClient({
  account: identity.account,
  transport: createPageTransport({
    evaluate: (fn, arg) => page.evaluate(fn, arg),
  }),
});
const inventory = await client.inventory();
const favorites = await client.favorites();
const albums = await client.albums();
const members = await client.albumItems(albums.items[0].albumId);
```

Methods: `inventory()` (including archived items), `favorites()`, `albums()`,
`albumItems(albumId)`, `trash()`, `item(mediaKey)`, `details(mediaKey)`, and
`hashCandidates(opaqueHashes)`. They never perform mutations. Pagination either
finishes with `complete: true` or throws; partial inventories are not returned as
complete. A completed traversal is not an atomic Google snapshot. Missing
favorite/shared/membership fields remain unknown. Album-item IDs and library
media IDs carry distinct namespaces. Hash lookup results are candidates and
always have `absenceProven: false`; the hash algorithm/coverage is unqualified.

The transport port accepts `{account, operation, mode, rpc, data}` and returns
`{account, status, body}`. It must bind the authenticated account before sending
and after reading, reject redirects/unapproved endpoints, bound responses and
timeouts, and never retry a write. Authentication failures and schema changes
trip the client circuit; create a new client only after resolving the cause.

Await `pageRequest` in direct callers: identity/preflight results may return
synchronously, while network reads are asynchronous.

## Capture an interaction

### Chrome or Edge extension

1. Run `npm run build:capture` or unpack the supplied capture-extension ZIP.
2. Open `chrome://extensions` (Chrome) or `edge://extensions` (Edge), enable
   Developer mode, and choose **Load unpacked** for the `capture-extension`
   folder containing `manifest.json` (under `dist` when building from source).
3. Open Google Photos, sign in yourself, then open the extension and choose
   **Start capture**. Chrome displays a debugger attachment banner. Avoid opening
   DevTools simultaneously because it may detach the extension.
4. Perform one operation on a disposable test image. Return to the extension,
   choose **Stop capture**, then **Download capture**.

After rebuilding an already installed unpacked extension, use **Reload** on its
Chrome/Edge extensions page. **Check connection** reads identity without sending
photo requests and has a ten-second deadline. A stalled check reports an error
instead of staying on "Working…". Other popup commands also have deadlines;
none is automatically retried. A timeout does not cancel an operation already
sent to the browser: check capture status before repeating a capture command.

The extension never uploads/favorites/deletes anything. **Read inventory counts**
is a separate explicit action that issues read requests; it does not produce a
retention-ready inventory because it does not enumerate every album's members.

Captures use passive CDP `Network` events and `getResponseBody`. They do not wrap
page functions, intercept requests, or replay traffic. Strings/opaque IDs are
replaced consistently within the capture; large numbers, times, and coordinates
are coarsened. Headers are allowlisted; cookies, bearer/CSRF/session tokens,
private media URLs and binary bodies are omitted. Upload tokens are not exported.
Protocol shapes and small numeric enums remain. Review any capture before sharing;
it is structural evidence, not an unredacted replay or a complete account snapshot.

Recording is limited to the chosen tab, selected Google Photos/upload hosts,
1 MiB response bodies, 1,000 entries and an 8 MiB exported-data budget. It does
not attach to child workers/frames or capture all possible upload hosts. A new
upload protocol may require extending the explicit host list after inspecting
DevTools. Detachment, limits and failed reads mark capture incompleteness.
Sanitized results stay in extension session storage/memory until downloaded or
the browser session ends; nothing is sent to PhotoFlow or another server.

Missing, oversized or malformed RPC request bodies and omitted structured response
bodies set `complete: false` with a generic `captureError`. Intentional binary-body
omission still applies. Capture completeness covers admitted traffic only; it does
not establish a complete account inventory or qualify a mutation transport.

### Existing debugging connection

If a browser-management session provides a CDP connection, forward it securely
to loopback rather than exposing the debugging port on a public interface:

```sh
node tools/capture.mjs --cdp http://127.0.0.1:9222 --out ./captures/upload.capture.json
```

Create the output directory first. Keep exactly one Google Photos tab open in
that browser profile. Perform one controlled interaction and press Ctrl-C. The
tool saves sanitized data with mode 0600 and disconnects without closing the
user's browser. It neither logs in nor changes photos. A browser connection has
not yet been configured on the deployed PhotoFlow host.

For an existing HAR, sanitize it locally before sharing:

```sh
node tools/sanitize-har.mjs private-input.har output.capture.json
```

The private HAR can contain account credentials and media data even if the
browser labels it sanitized; do not commit it. The converter refuses to overwrite
output and makes no network requests. Exported captures are gitignored.

## Mutations and recovery

`MutationExecutor` implements `favorite` (true/false), reversible `trash`, and
`restore`. There is no permanent deletion, arbitrary RPC method, or automatic
retry. Pass a transport, durable journal, clock, and an `inspect(plan)` function.
The inspector must freshly establish account, media/dedup IDs, local revision,
full SHA-256, ownership, favorite/trash state and preservation facts. For cloud
trash it must also prove no curated album membership, local original/companions,
matched metadata, and an independent verified backup. Unknown is never false.

Each plan contains `id`, `account`, `type`, `target` (`namespace: library-media`,
`mediaKey`, `dedupKey`), local `revision`, `sha256`, and a boolean `value` for
favorite changes. Plans are frozen before handing them to adapter code.

Writes require explicit qualification: `{account, protocolVersion, operations,
expiresAt, evidenceSha256}`. This is an operator assertion pointing to real test
evidence, not proof generated by the library. Do not fabricate it to bypass a
missing live test. Qualification is account/operation/version bound and expires.
The supplied browser evaluator rejects writes regardless of this setting; a
qualified mutation transport must be added after the disposable live pilot.

The journal port has async `lock(account) -> release`, `get(id)`, `put(record)`,
`pending(account)`, and `findUpload(account, sha256)` methods. The executor holds
the lock across preflight, durable intent, write, read-back and completion.
`FileJournal` in `@photoflow/google-photos/node` uses exclusive writer locks,
atomic JSON replacement, file/directory fsync, and mode-0600 records. Keep it on
a local filesystem supporting those operations. A crash leaves a lock requiring
operator investigation; it is never silently stolen. `MemoryJournal` is only a
test/reference adapter, not suitable for production mutations.

Native Windows journal qualification currently fails the private-directory check;
do not disable that guard. Use a suitable POSIX filesystem or a separately qualified
durable adapter. See the [browser qualification report](docs/qualification/2026-10-30-browser-session.md)
for the observed Windows and Linux results.

A lost acknowledgement or failed postcondition persists an unknown outcome and
blocks later writes, including after restart. `executor.reconcile(id)` performs
read-back only; it completes the intent only when the desired state is proved.
It never resends the write. Unresolved outcomes remain blocked. No client can
guarantee that Google has not already acted before returning an error, or offer
atomic compare-and-swap against concurrent edits in Google's UI.

## Uploading and metadata wait

`OfficialUploader` implements the documented Library API byte-upload followed by
single-item `batchCreate`. It has separate ports for account-bound OAuth HTTP,
fresh local/remote preconditions, source-byte verification, and remote read-back.
It requires the same durable journal and an `upload` qualification. Configure
OAuth through an eligible integration; this package does not create a Cloud
project, request consent, store refresh tokens, or bypass API restrictions.

`createOAuthTransport` accepts a credentials provider returning the account
identity established by its OAuth flow and the current access token. It allows
only the exact upload/create/read-item endpoints and rejects redirects. Tokens
are attached only after validation and are not returned or journaled. The
credentials provider must verify account identity; a caller-supplied string
alone is not authentication evidence.

An upload plan contains `id`, `account`, `revision`, `sha256`, `filename`,
`mimeType`, and byte `size`. Its source exposes `body`, `size`, and async `verify()`.
`openFileSource(path, sha256)` supplies a Node stream that hashes exactly the bytes
consumed and verifies the original's signature; always close the source in a
`finally` block. Creation cannot proceed before those bytes verify. HTTP status,
per-item status, upload-token correspondence, returned media ID, and remote
existence are checked before recording `uploaded` with `awaitingMetadata: true`.

Receipts are deduplicated by account/content even when a new operation ID is
submitted. Missing Takeout metadata never alone triggers a second upload. A
previously uploaded item that has since disappeared requires reconciliation;
automatic republishing after deliberate cloud removal is not implemented.
Raw upload streams support photos up to 200 MB and videos up to 20 GB, subject
to Google's format support. Resumable chunk uploads and browser-based uploads
remain unimplemented; interrupted raw uploads stop for reconciliation.

`uploader.reconcile(id)` can finish a recorded creation receipt through read-back
without sending media again. If creation acknowledgement was lost before a remote
ID was recorded, it remains blocked for explicit identity reconciliation.

## Retention rules and remaining integration work

`decideRetention(facts)` is a pure decision function returning an action and
reasons. It distinguishes unknown/absent/present remote content, missing versus
invalid Google metadata, current favorites and curated albums, verified local
originals/companions/backups, and pending/unknown/completed uploads. Removal is
only a `review-trash` candidate. Nothing executes a policy decision automatically.

The PhotoFlow application still needs a connected-account setup flow, authoritative
remote identity mappings, export/account attribution, metadata-round-trip ledger
updates, and its reconciliation/review UI. Album writes, browser upload, full
Takeout orchestration, and unattended browser session management are not included.
Live hash semantics, upload ID mapping, mutations, and Takeout enrichment need
qualification. These boundaries are explicit rather than inferred from a
successful unit test. See the repository's ADR 0003 for the application design.

## Upstream and references

Protocol knowledge and sanitized fixture shapes derive from Google Photos Toolkit
3.3.0, commit `6db9ab355e4797327e4078cf87a2b6994d36cf73`; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). It is not a runtime dependency.
No account data from this deployment is committed in fixtures.

- [Google Photos Toolkit](https://github.com/xob0t/Google-Photos-Toolkit)
- [Official uploads](https://developers.google.com/photos/library/guides/upload-media)
- [Chrome debugger API](https://developer.chrome.com/docs/extensions/reference/api/debugger)
