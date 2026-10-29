# Storage, identity, and consistency

## Authority and layout

Original media, adjacent records, and explicit user decisions remain portable
filesystem data. The read catalog, search index, and thumbnails are rebuildable.
Losing an index must not lose folder intent, overrides, trash, or audit history.

```text
PhotoLibrary/
  .photoflow/
    library.json                 identity and writer compatibility requirement
    lock                         common lock for every metadata/media writer
    pending/                     operation intents and recovery manifests
    folders.json                 authoritative user-folder IDs and keep-empty intent
    jobs/                        durable mutation job requests/results
    uploads/                     hidden partial transfers and upload manifests
    source-locations.json        authoritative current locators for source occurrences
    trash/<operation-id>/        media, records, folder contents, restore manifest
  inbox/web/<batch-id>/           committed automatic uploads and source JSON
  photos/YYYY/MM/<uuid>.<ext>
  undated/<uuid>.<ext>
  review/duplicates/...
  folders/<user-chosen-path>/     manually organized media and persistent folders
```

Source JSON supplied with a manual-folder upload also goes in an immutable
per-batch source area beneath `inbox/web/`; original uploaded relative paths are
retained as provenance. The source-location mapping associates them with records.
This keeps raw source JSON available after user-folder rename/trash operations.
Browser upload intake MUST prevent ordinary scanning from processing a batch
until its publication manifest says the associated files are ready.

Local SSD defaults: `/var/lib/photoflow-web/catalog.sqlite` for the disposable
catalog, `/var/lib/photoflow-web/sessions.sqlite` for revocable sessions, and
`/var/cache/photoflow-web/` for derivatives and temporary exports. These are
configuration defaults, not paths to create while authoring the spec. Do not put
SQLite on an SMB share. Bind each derived store to the library ID and schema.

## Record and folder contracts

Keep existing record UUIDs, full hashes, source observations, and histories.
Extend records with validated optional fields:

| Field | Contract |
| --- | --- |
| `placement` | `{mode: "automatic"}` or `{mode: "manual", folder_id: UUID}` |
| `lifecycle` | `active` or `trashed`; missing means active during migration |
| `overrides.title` | String or null; null suppresses imported title |
| `overrides.tags` | String array; empty array explicitly clears tags |
| `overrides.favorite` | Boolean, default false |
| `overrides.location` | Null or `{latitude, longitude, altitude_m?}` in WGS84 |
| `overrides.display_rotation` | 0, 90, 180, or 270 clockwise after EXIF orientation |

Existing override fields remain supported. Date API values use an explicit
precision object and are translated to the compatible stored capture-time string;
add `capture_time_precision` alongside it so a date-only value is not fabricated
as midnight. Preserve unknown timezone and the supplied numeric offset. Resolve
new fields with provenance and defaults; add validator/resolver coverage before
the web API can write them. Rotation is a display instruction, never a change to
the original bytes.

`folders.json` contains schema/library IDs and entries with `folder_id`,
`parent_id`, `name`, current relative path, `keep_empty: true`, creation actor/time,
and revision. Its records survive catalog deletion. `folders/` is a protected root.
It has its own persistent registered ID, available as a parent for new folders.
Register external directories within `folders/` during reconciliation, assigning
stable IDs and keep-empty intent; ambiguous manual relocations are reported.
Automatically generated or source directories have paths but no user-folder ID.
They are navigable through path-based read endpoints, with mutation capabilities
set to false. Unregistered external files are shown as pending ingestion or
unmanaged counts, not silently excluded from folder totals.

New external media discovered inside a registered `folders/` directory receives
manual placement for that directory before normal planning. Moving an existing
record into that namespace externally requires an unambiguous reconciled identity
before updating its placement intent. A scan must not drain a user folder merely
because the upload arrived over SMB instead of the browser.

Display titles never rename physical UUID files. Manual placement overrides date
and duplicate-review placement; a later date correction cannot undo the move.
Clearing manual placement deliberately returns to normal policy. All duplicate
occurrences remain represented regardless of their placement.

## Revision and actor

A record ETag is the SHA-256 of its current authoritative sidecar bytes; folder
ETags reflect the folder entry and relevant subtree membership revision. Mutations
require `If-Match`. Revalidate under the writer lock immediately before execution,
including queued work. Stale requests fail with a conflict and leave the draft
recoverable. A changed file signature during work causes deferral/reverification.

Every user mutation appends an event containing actor UID and username, request
ID, job/operation ID, timestamp, relevant before/after values, and reason. System
events identify the service. Credentials, session tokens, and password data never
enter records or logs. Use operation IDs to prevent duplicate recovery events.

## One owner of writes

API handlers validate and persist requests. One coordinator applies mutations
through shared domain services while holding the existing library lock. Cron,
manual CLI, recovery, and web jobs obey the same lock. Readers use the last
committed catalog snapshot and tolerate a record temporarily moving. Thumbnail
workers read stable content and only publish disposable derivatives.

For a mutation: persist intent → recheck identity/revision/source → apply
no-overwrite filesystem operation → publish records and authoritative intent →
update catalog → mark job complete. Atomic file replacement and directory fsync
are required where supported by the existing adapter. A multi-file operation is
recoverable, not magically atomic to external SMB clients. During recovery,
affected objects are marked busy; no conflicting web mutation may execute.

Directory rename/move uses one no-overwrite directory move plus journaled updates
for descendant record paths, registry entries, and source locators. Preserve all
contents, including unknown files. Preflight checks inventory, revisions,
normalized collisions, forbidden descendants, active uploads, symlinks and mount
boundaries. Recheck before mutation; changed subtrees are deferred. Cross-device
moves are unsupported in v1. Never replace an occupied path or merge directories.

Raw original paths remain immutable evidence. Mutable source locations live in
the source-location mapping; reverse dependencies include records that inherited
a source through duplicate merging. Ordinary source-folder renaming via the GUI
is out of scope in v1. External source moves are reconciled when evidence is
unambiguous; otherwise Activity reports unresolved sources and preserves records.

## Trash and duplicates

Trashing a photo moves that occurrence and its sidecar under protected state,
stores its original path/placement/actor in a restore manifest, and records the
lifecycle change. The original source JSON remains available. Trashing a user
folder preserves its entire subtree and registry entries. Recovery and catalog
rebuild read trash manifests explicitly; normal discovery never sees trashed
media. Trash consumes space and appears in capacity statistics.

Before trashing a canonical duplicate keeper, choose a verified active copy using
the normal deterministic keeper policy, transfer any provenance needed for
continuity, and relink surviving copies in the same recoverable job. Keep human
overrides attached to their occurrence. Exclude the entire frozen trash selection
or folder subtree from promotion candidates, including items not yet processed.
If all copies are selected, no active keeper remains and no promotion is needed.
Preview warns when a retained copy will remain visible. Trashing all copies is a
separate explicit selection. Restore
keeps the original record ID; it does not displace a new keeper automatically.

Restore verifies content and reserves destinations. Occupied destinations return
a conflict; the user may choose another user folder, preserving UUID filenames.
An unavailable original manual folder must be recreated explicitly or replaced
with another target. No automatic trash expiration. Administrators may purge a
selected trash operation after confirmation of item/byte counts; purge is durable,
restartable, and permanently deletes only the exact items in that manifest.
Repeated purge returns the existing outcome. Retain a tombstone/audit receipt
after purge. Purge must not remove raw source documents used by active records.

## Reader catalog and rollout

Catalog fields include record ID, path, revision, lifecycle, hash, dimensions,
preview state, resolved/searchable metadata, duplicate membership, folder ancestry,
and source dependencies. HTTP requests query indexes rather than walking the
library or opening every sidecar. Publish catalog changes only after authoritative
commits. On restart, replay journals and refresh affected catalog rows; rebuild
into a second database and swap only when complete.

Current PhotoFlow does not implement manual placement, persistent empty folders,
trash/promotion, new metadata fields, targeted jobs, or compatibility gates.
These extensions MUST precede web mutations. Introduce a library format/writer
capability gate that old binaries actually reject before writing: merely adding
an ignored `minimum_version` field is insufficient. A version-2 library marker,
with explicit migration from version 1, provides this rejection in the current
CLI. Update CLI and web together, back up authoritative metadata before migration,
and test that the old writer refuses the migrated marker. No migration occurs
merely by starting a read-only web preview.
