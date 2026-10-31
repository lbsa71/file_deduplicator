# Live inventory-count read succeeded, 2026-10-31

Starting `origin/main`: `e6d5684da3fa1d719b939d50b1bb7f58beb2d094`.
Chrome 156.0.8078.74 on Windows; account alias `personal-account-A`.
The operator reloaded the repository-built extension after the UTF-16 framing
and strict `e`-trailer corrections.

One explicit **Read inventory counts** attempt completed. Native popup inspection
returned:

```json
{
  "photos": 11431,
  "favorites": 277,
  "albums": 15,
  "complete": true,
  "retentionReady": false
}
```

These are live counts returned by the existing strict client, not fixture values
or counts inferred from visible thumbnails. The action awaits library inventory,
favorites and albums sequentially. Each must validate its RPC, page rows and
continuation cursors through a terminal page before the popup can return this
success. The library count exceeds the 500-row request size and therefore
demonstrates successful continuation. No page-by-page network trace was recorded
for this attempt, so exact per-page timings and transport records are not claimed.
The client does not retry reads automatically.

The result verifies that the corrected framing and trailer handling work in this
signed-in account for the inventory, favorites and album-list methods. It does
not establish a stable snapshot against concurrent Google-side changes or qualify
every Google account/version. This count action does not enumerate album members,
inspect individual item details, bind upload identifiers or evaluate preservation
facts. Its explicit `retentionReady: false` remains authoritative: it must not be
used to authorize removal or infer absence from uninspected relationships.

The previous code verification remains: all 80 package tests passed on Linux
Node 22.23.4, and the actual Chromium 156.0.8078.4 extension test passed with
synthetic Unicode framing and the observed trailer. This follow-up changes only
documentation. Diff and relative-link checks were performed; no code tests were
repeated. Native Windows journal privacy qualification remains unresolved.

No photos or albums were changed and no disposable remote items were created.
Credentials, emails, media IDs, raw HARs and personal screenshots are not included.
The earlier reduced, aliased live fixture and its redactions remain documented
in [the fixture notes](../../test/fixtures/live/README.md).

Next read qualification needs bounded, account-bound calls for a deliberately
selected album's members and an exact item's details, plus correspondence of
library and album-item identifiers. The current popup has no controls for those
methods; ordinary UI captures previously omitted the main RPC response bodies.
Capture returned read results for those methods before claiming their contracts
or complete curated membership. Mutation and upload qualification still require
synthetic media in an isolated test library. The personal library stays read-only.
