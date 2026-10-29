# Acceptance tests and delivery

Strict TDD applies to new behavior. Write failing tests before production changes,
using injected filesystem, clock, IDs, authentication, decoder, index, and reporter
ports. Keep deterministic path/hash/metadata rules real in unit tests. Run actual
filesystem and subprocess contracts separately; use scratch libraries for all
destructive scenarios. Preserve the existing 108 service tests.

## Required scenarios

| ID | Scenario and observable result |
| --- | --- |
| A01 | Allowed Linux user logs in; wrong password, empty password, expired account/password, root, missing group and unavailable broker deny access |
| A02 | Reader cannot mutate; editor cannot purge/admin-verify; bypassing UI still returns 403; current role checked for queued execution |
| A03 | CSRF, forged Origin, expired/revoked session, unauthorized media/range/export/SSE fail; group revocation applies within 60 seconds |
| B01 | 24k-record timeline/search/folder pages use catalog indexes without full walks/sidecar parsing; cursor is stable across new arrivals |
| B02 | Mobile/keyboard selection, viewer navigation, zoom, Escape, focus restoration, URL reload and filter/scroll restoration work |
| U01 | Upload photo plus Takeout JSON: people/unknown source fields and original filename preserved; requested target policy respected |
| U02 | Interrupted chunk upload resumes at acknowledged offset; repeated chunks/finish/commit return same occurrence; different bytes conflict |
| U03 | One ready group appears while later groups upload; late JSON enriches that occurrence and affected keeper without pixel regeneration |
| U04 | Disk-full, external free-space consumption, wrong total length, checksum mismatch, type mismatch, path traversal, giant JSON fail safely |
| U05 | Upload expiry/cancel removes only staging; restart at each publication step creates no second original or partial visible photo |
| M01 | Set/clear/reset people and date survive repeated rescans; reset restores imported values; timezone-unknown/date-only precision survives |
| M02 | Concurrent editors: second stale revision fails, draft retained; source JSON/history/identity cannot be edited through metadata API |
| M03 | Favorite/title/tags/location/rotation persist and rebuild correctly; only pixel-affecting edits regenerate derivatives |
| F01 | Create empty folder, scan twice, restart and rebuild catalog: folder remains with same ID |
| F02 | Manual photo move, external SMB arrival in a user folder, date change and duplicate discovery preserve manual placement; explicit automatic placement restores policy |
| F03 | Folder rename/move updates descendants and source mappings; interrupt each journal boundary and recover without loss or duplicate events |
| F04 | Case/Unicode collision, parent-into-descendant, symlink, mount crossing, protected tree and occupied destination are rejected |
| T01 | Trash occurrence/folder, scan/rebuild, restore: IDs, bytes, metadata and hidden/unmanaged folder contents survive; no resurrection |
| T02 | Trash a folder containing keeper and one duplicate with another outside: promotion excludes all selected members; crash recovery leaves no dangling active relationship; restore does not steal keeper status |
| T03 | Restore to occupied destination fails without overwrite; explicit alternative succeeds; no scheduled purge occurs |
| T04 | Admin purge deletes only selected manifest contents; restart/retry is idempotent; active source JSON and other copies survive |
| D01 | Original and range downloads match source bytes; export collisions are disambiguated with manifest; metadata export is explicit |
| D02 | Selection export is bounded, authorized, resumable and expires; source changes fail instead of silently mixing revisions |
| P01 | Real JPEG/PNG/WebP/GIF/TIFF/HEIC orientation/color fixtures produce correct levels; RAW/video failures show honest placeholders |
| P02 | Missing thumbnail enqueues once for concurrent requests; stale decode results discarded; filename/people changes cause zero regeneration |
| P03 | Warm grid meets access/latency budgets; worker timeouts, huge images, corrupt files, cache-full and worker death remain isolated |
| J01 | Normal/metadata/verify/catalog/thumbnail jobs have distinct effects; busy lock queues; cancellation stops only at safe boundaries |
| J02 | Watcher own events do not loop; arrivals during pass are queued; missed events/startup/overflow/remount trigger reconciliation |
| J03 | New duplicate matches existing collection; source JSON change reaches all dependents; missing ExifTool preserves previous extraction |
| O01 | USB unplug/remount preserves jobs and cannot write a fallback library; wrong volume marker refuses writes |
| O02 | Delete catalog/cache, rebuild from authoritative filesystem, recover all active/trash/folder intent and overrides |
| O03 | Old CLI refuses migrated library before any mutation; new CLI and web share locking and recover one another's operations |

PAM deployment tests use deliberately provisioned test accounts and the actual
broker; fixtures contain no real passwords. Decoder and storage tests exercise
the actual Linux/exFAT target on an isolated test root. Browser tests cover desktop
and mobile Chromium plus a WebKit smoke run for upload/view/download. Run real
SMB transfer event tests before relying on watcher scheduling.

## Delivery slices

1. **Read-only vertical slice:** session/broker contract, authorization, catalog
   rebuild, timeline/folders/search, viewer and original download. Include required
   multilevel thumbnails immediately so the first UI is representative. Test cold
   and warm budgets before importing all media into the cache.
2. **Safe mutation foundation:** library compatibility gate, validated new fields,
   revision/actor events, manual placement, persistent folders, operation journals,
   trash/restore/keeper promotion. Prove recovery using failing tests first.
3. **Editor workflows:** resumable media/JSON upload, metadata forms/reset, favorites,
   tags, folder CRUD, bulk actions, exports and visible conflict handling.
4. **Unattended operation:** durable force-rescan modes, targeted dependency work,
   watcher/debounce/reconciliation, cancellation/retry, settings and diagnostics.
5. **Release validation:** scratch exFAT/PAM/SMB integration, accessibility checks,
   capacity/failure tests, migration rehearsal, full performance report and backup
   restore rehearsal. Enable production mutations only after these pass.

All slices are needed for the first release requested here; the read-only slice
is a useful interim milestone, not completion of CRUD. No live-library migrations,
trash purges, new Linux accounts, or service deployments are performed by writing
this specification.

## Release artifacts

Ship pinned dependencies, API/OpenAPI contracts, runnable tests, deployment units
and configuration example, codec capability output, migration/rollback guide,
operator runbook, and measured performance report. The report includes number of
records, source formats, cold/warm cache state, filesystem calls/bytes, worker
resources, and concurrent clients. Do not label targets as achieved without data.
