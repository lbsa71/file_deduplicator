# PhotoFlow

Offline places: add `--places --geodir /path/to/Geolocation500` to `photoflow run`.
This resolves stored EXIF/Takeout coordinates and writes an ordered `resolved.place`
hierarchy (locality, administrative areas, country, continent) with provenance.
`--no-move` supports metadata-only backfills. ExifTool and its pinned GeoNames
database are the only lookup dependencies; no network geocoding runs. See the
[place ADR](../web/spec/adr/0002-place-hierarchies-and-offline-geocoding.md).

A small batch service for a filesystem photo library. Drop media into any folder
under the library root; each pass updates adjacent JSON records, preserves source
metadata, finds exact duplicates, and organizes files into date folders.

The design comes from the **Fotohantering** conversation. [PLAN.md](../../PLAN.md)
records the decisions and follow-on work. This first implementation uses Python
3.11+ with no runtime dependencies. An installed ExifTool is optional.

## Start with a scratch library

Run from the service directory without installing anything:

```bash
cd apps/photoflow
```

```bash
mkdir -p /tmp/PhotoLibrary/inbox
python3 -m photoflow init /tmp/PhotoLibrary --library-id family-photos
# Copy a small extracted Takeout sample, with its JSON and folder structure,
# into /tmp/PhotoLibrary/inbox before running the following commands.
python3 -m photoflow run /tmp/PhotoLibrary --dry-run
python3 -m photoflow run /tmp/PhotoLibrary --no-move
python3 -m photoflow run /tmp/PhotoLibrary
python3 -m photoflow search /tmp/PhotoLibrary Christmas
```

`--dry-run` writes nothing. It reports proposed moves, errors, and unmatched
source JSON. IDs assigned to new files in a preview are provisional.
`--no-move` saves metadata and proposals without moving media; it can repair
sidecar locations. Neither mode replays pending media moves: finish recovery
with an ordinary `run` first.

The default quiet period is 30 seconds. Use `--settle-seconds 0` for completed
scratch fixtures. For unattended uploads, transfer under an unsupported suffix
such as `.part`, finish the associated JSON, then rename the media to its final
extension. A quiet period cannot prove that a paused upload is complete.

To install the command in a virtual environment from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e apps/photoflow
.venv/bin/photoflow --help
```

## Library layout and identity

```text
PhotoLibrary/
├── .photoflow/
│   ├── library.json                 # Persistent library identity
│   ├── lock
│   └── pending/                     # Recoverable operation intents
├── inbox/                           # Ordinary source folders
├── photos/2018/12/
│   ├── <record-uuid>.jpg
│   └── <record-uuid>.jpg.photo.json
├── undated/<record-uuid>.jpg
└── review/duplicates/<keeper-uuid>/<duplicate-uuid>.jpg
```

The record UUID stays fixed. SHA-256 identifies the current bytes. The complete
root-relative path locates those bytes. A better capture date may move a record
between folders without changing its UUID or repeating embedded extraction.
Unknown dates go to `undated`; extensions become lowercase. People, albums, and
original names remain metadata rather than deciding a file's physical location.

The library marker is required before a pass can write anything. Initialization
requires an existing root and never replaces its identity. Scheduled runs can
use `--expect-library-id family-photos` to detect an unexpected library or a
missing volume marker. Paths in records remain valid when the whole library
moves between machines.

## What a record retains

Each `<media>.photo.json` contains:

- `schema_version`, `library_id`, and `record_id`.
- `file`: relative path, size, SHA-256, first-1-KiB hash, and the observed stat
  signature. `ctime_ns` means filesystem metadata-change time, not creation time.
- `sources`: original filenames and paths, stable source IDs, and imported JSON
  documents with path, scope, digest, and all original fields. Distinct document
  revisions remain available.
- `resolved`: capture time, people, albums, description, and sourced assertions.
  Conflicting assertions remain in provenance; the first eligible assertion
  wins for scalar fields, while people and albums are unions.
- `overrides`: explicit human values that automated resolution must respect.
- `stages`: independently keyed and versioned results/checkpoints.
- `history`: sequenced events with event/run IDs, timestamps, and relevant
  changes, including discovery, verification, metadata changes, duplicates,
  reconciliation, planned/completed moves, and failures.

An unchanged pass leaves the entire photo sidecar untouched. Its
`last_scanned_at` is the most recent observation published with a substantive
record change; `last_processed_at` records the last published processing state.
`.photoflow/last-run.json` records the latest successful writable pass's start,
completion, and record counts. Failed/deferred results remain available in the
command output. `--audit-every-scan` explicitly persists per-file scan events.
Search covers original filenames as aliases, plus resolved dates, people,
albums, and descriptions. It also searches review records.

`resolved` is the convenient aggregated metadata snapshot. For example,
`resolved.people` is a plain array of unique names. It appears near the top of
the sidecar; raw sources and processing state follow, with history at the end.
`resolved.provenance` links each assertion back to its evidence.

To correct a managed sidecar, stop concurrent passes and edit only `overrides`:

```json
{
  "capture_time": "2018-12-24T19:04:00+01:00",
  "people": ["Alma", "Stefan"],
  "albums": ["Christmas"],
  "description": "Christmas at Grandma's"
}
```

Place that object under the sidecar's `overrides` key. An empty people/album list
suppresses imported labels; `capture_time: null` explicitly leaves the date
unknown. Resolution changes are logged. Avoid editing identity, hashes,
checkpoints, or history.

## Takeout and embedded metadata

The importer reads `<original-name>.supplemental-metadata.json` and the older
`<original-name>.json` convention. A truncated supplemental filename can be
matched by its `title` within the same directory when the match is unique.
Immediate-folder `metadata.json` is preserved separately; its `title`, when
present, is an album assertion. Folder membership never creates a person label.

Takeout `people[].name` becomes photo-level person labels. `photoTakenTime`
supplies a capture timestamp; Google upload/creation time is not substituted.
Takeout `favorited: true` becomes `resolved.favorite: true`, with its source in
provenance. A favorite assertion in any current source is retained; an explicit
`overrides.favorite` value takes precedence, including `false` to unfavorite it.
Resetting that override restores imported resolution. Resolver version 2 refreshes
existing records without requiring new embedded extraction or moving files.
Original JSON is never rewritten or removed. Its parsed content and unknown
fields are embedded in the managed record. Retain the original Takeout ZIPs for
the original byte representation and full export context.

Each pass revisits original source paths, so JSON arriving after a media move
can still enrich its record. This also applies to sources merged from exact
duplicates. Prior revisions are retained, while the latest revision at each
source path supplies current assertions. Arbitrary cross-directory/archive-part
matching is not implemented; unmatched JSON is reported and retained. Extract
archive parts without flattening folders or overwriting repeated names.
Numbered collision variants such as `photo.jpg.supplemental-metadata(1).json`
also remain unmatched: their numbering is not treated as proof of which media
occurrence they describe. The real export contains these variants, including
some with people labels; those source files remain preserved for reconciliation.

Use `--exiftool` to extract embedded metadata with an installed `exiftool`
executable. Its version participates in caching, and its returned grouped JSON
is retained. The adapter follows [ExifTool's JSON output interface](https://github.com/exiftool/exiftool/blob/master/html/exiftool_pod.html).
Resolution prefers embedded `DateTimeOriginal` (including a composite timestamp
or companion `OffsetTimeOriginal` when available), then QuickTime creation time,
then Takeout capture time; assertions from other sources remain visible. EXIF
dates without an offset remain timezone-unknown; the service never supplies the
server's timezone. Date folders use the calendar date as recorded. Without
ExifTool, Takeout import, hashing, reconciliation, and placement still work.

## One pass

```text
lock → recover → inventory/reconcile → freeze queue
     → observe → fingerprint → extract/resolve → exact duplicates
     → reserve locations → apply moves → prune empty directories → summary
```

Every pass scans the entire configured library root, including `inbox`,
`photos`, `undated`, and `review`. The inbox has no separate scanning behavior;
it is an ordinary folder whose media will be placed elsewhere.

One filesystem walk collects file paths, initial stat signatures, and directory
candidates together. Pending-operation recovery scans its own small state
directory separately. Stages run across the whole batch in order. New arrivals wait for the next pass;
a move updates the existing queue item. Stat signatures cache hashes; `--verify`
forces full hashing to detect changes hidden behind unchanged stat information.
Reads and moves recheck source stability. Embedded extraction is keyed by
content hash and reader version; imported JSON and overrides independently
invalidate resolution. Scan timestamps and placement changes do not invalidate
embedded extraction. Sidecars are serialized and saved only when an event or
checkpoint changes their state; timestamp-only observations cause no writes.
Stages must emit `Context.event` or `Context.complete` for record mutations.
Checkpoint writes remain durable between stages and extraction batches.

Imported JSON is cached between passes under `.photoflow/source-cache/` in up to
256 small shards. A hit requires an unchanged complete stat signature, matching
library/schema identity, and a valid cached-payload checksum. Source stability
is rechecked around lookups. Changed files are reread; unknown fields and prior
source revisions remain preserved. Corrupt caches produce warnings and rebuild
from originals. Cache files are disposable and never replace the source JSON or
managed records. Only changed shards are rewritten. `--verify` bypasses both
media-hash and imported-JSON stat caches; previews never save caches or reports.
Shared source/album JSON is still read at most once per pass when a read is due.
Embedded metadata reads use batches of up to 64 dirty files per ExifTool
process. Failed batches fall back to individual reads, and changed files cannot
reuse prepared metadata. Metadata checkpoints are saved after each batch so an
interrupted large pass can reuse completed extraction work.

Exact matching uses size, a first-1-KiB digest, complete SHA-256, and byte
comparison before establishing a duplicate relationship. All newly managed
files receive full hashes because placement and later repair need them. Cached
records still participate in the current batch's matching. Existing canonical
files and previously processed records are preferred as keepers; source metadata
and names are merged into the keeper. Both records and both binaries survive.
By default duplicates move to
`review/duplicates`; `--duplicates keep` leaves them in the ordinary date layout.
Review files remain part of subsequent scans and verification.

Reconciliation verifies media and sidecars moved together, media moved alone,
and sidecars moved alone. Hash-based repairs require unambiguous associations;
copied record IDs and ambiguous equal-byte candidates are reported. Missing
media never causes metadata pruning. Destination reservation compares case and
Unicode-normalized paths; actual moves also reject existing destinations.

After a successful writable placement pass, empty directories seen at the start
of the pass are removed from the bottom up. The library root, `inbox` itself,
application state, Finder metadata directories, symlinks, and other filesystems
are preserved. Only atomic `rmdir` is used: a folder containing source JSON,
hidden files, or a newly arrived file stays intact. Folders created after the
initial inventory wait for another pass. `removed_directories` lists removals
in the JSON summary. Preview and metadata-only passes do not prune; processing
errors or deferred files skip cleanup. Cleanup failures appear as warnings.

## Recovery and supported storage

On Linux, the local adapter uses `renameat2(RENAME_NOREPLACE)` for moves and new
metadata files. Hard links are not required: ext4 and the mounted exFAT USB drive
have both been tested. The kernel, C library, and filesystem must support that
operation; an unsupported operation fails instead of using an unsafe
check-then-rename fallback. Existing sidecar updates use atomic replacement.
Other POSIX platforms retain the original hard-link implementation.

Storage must support advisory locks and file/directory flushing, and each move
must stay on one filesystem. The adapter rejects symlinks and escaping paths.
Cross-device moves fail without overwriting or deleting the source. Media
formats are selected by suffix, not by successful decoding; use
`--extensions jpg,jpeg,heic,mov,mp4` to narrow the default media set. JSON is
reserved for metadata and cannot be selected as media.
Finder resource forks (`._*`), `.DS_Store`, `.AppleDouble`, and `__MACOSX`
folders are ignored and retained. Application state directories are excluded
from ordinary scans, including extraction state nested beneath an inbox.
Reserved sidecar-write temporary names (`.photoflow-tmp-*`) are also excluded.

Every media move or sidecar relink first saves its intended final record in
`.photoflow/pending`. Linux moves use a single no-overwrite rename. Recovery
verifies whichever media path exists, publishes the destination sidecar, and
removes the old sidecar and journal. Existing journals from the original
link/unlink implementation remain recoverable when both names reference the
same inode. Files and relevant directory entries are flushed. Replaying an
operation retains a single completed-move event. The application journal
supports recovery from process interruptions; it does not turn exFAT into a
journaled filesystem or replace an independent backup.

If recovery encounters different bytes, independent files at both paths, a
foreign sidecar, or missing media at both locations, it retains the journal,
reports the conflict, and stops before discovery. Inspect those paths and the
journal; resolve the underlying conflict, then run again. Never discard a
journal to bypass a conflict without understanding its recorded paths.
Managed/imported JSON reads are bounded to 32 MiB per file.

The lock covers normal writable passes. A busy invocation exits successfully
with `locked: true`; a dry run takes no lock and is a best-effort read-only
preview. Root identity and complete enumeration are checked before processing.
The command emits JSON: exit 0 means a completed/locked pass, exit 1 means
reported processing errors, and exit 2 means CLI/setup failure. Warnings include
deferred files and unmatched source metadata.

Use `--stats` for access counters and elapsed time:

```bash
python3 -m photoflow run /path/to/PhotoLibrary --exiftool --stats
```

The summary includes source-cache hits, misses, and shard writes. With `--stats`,
`io` also reports inventory calls and entries, explicit stat/existence calls,
read opens/calls/bytes by media, sidecar, source JSON, and application state,
atomic writes and payload bytes, moves, and empty-directory removal attempts.
These measure the filesystem port, including the single successful-run report
write. They exclude adapter-internal path checks, ExifTool's own file access,
kernel syscall counts, and physical device I/O. Every pass still inventories
the whole library and reads its managed sidecars. Conservative stat changes on
exFAT can cause rehashes even when file bytes have not changed.

## Run periodically

The service itself is a finite command. For cron, after installation:

```cron
*/5 * * * * /opt/photoflow/.venv/bin/photoflow run /mnt/photos/PhotoLibrary --expect-library-id family-photos --exiftool
```

For Ubuntu, [deploy/photoflow.service](deploy/photoflow.service) and
[deploy/photoflow.timer](deploy/photoflow.timer) provide a five-minute systemd
timer. Adjust the user, executable, mount, library path, and identity; remove
`--exiftool` if it is not installed. Install the units under `/etc/systemd/system`,
then run `systemctl daemon-reload` and `systemctl enable --now photoflow.timer`.
Inspect results with `journalctl -u photoflow.service`. These are deployment
examples; nothing is installed or enabled automatically.

## Verified Takeout extraction

The separate operational helper in `scripts/extract_takeout.py` extracts the
current `takeout-20261028T123735Z-1-001.zip` through `025.zip` export. It accepts
only finalized ZIP names, preserves paths directly under the chosen root, and
records completed archive numbers independently of whether their ZIPs remain.

```bash
python3 -m scripts.extract_takeout /mnt/usb/tx takeout-20261028T123735Z-1-001.zip
# Explicit archive cleanup after integrity and extracted-output verification:
python3 -m scripts.extract_takeout /mnt/usb/tx takeout-20261028T123735Z-1-001.zip --delete
```

This helper uses archive/path locks to coordinate overlapping entries, checks
member CRCs and sizes while streaming, then re-reads extracted files to verify
their SHA-256 hashes. Differing existing outputs are preserved and reported;
their ZIP remains available. Absolute/escaping paths, symlinks, special entries,
and paths targeting its own state are rejected. No-overwrite publication also
works on exFAT. Completion records bind archive SHA-256, central-directory
membership, and extracted-output hashes. Interrupted cleanup can resume.

`.takeout-extract/completed/NNN.json` contains the durable verification report;
`running/` and `failed/` contain progress and errors. A completion record can
precede archive cleanup, so `archive_deleted` distinguishes those states.
The core `photoflow run` command does not invoke this helper or delete ZIPs.

For older archives in a working copy, the helper also exposes a general API:

```python
from scripts.extract_takeout import extract_legacy_archive

extract_legacy_archive(
    "/path/to/working-copy",
    "albums/holiday.zip",
    archive_number=1,
    output_prefix="_expanded/holiday",
    delete=True,
)
```

Use a stable job number and output prefix for retries. Parts of the same split
export can share an output prefix; unrelated archives can use separate prefixes
to preserve their context. Cleanup removes only the verified working-copy ZIP.
The supplied source folder remains available as the original backup.

## Development and extensions

Run these commands from `apps/photoflow/` (or use `make test` at the repository root):

```bash
python3 -m unittest discover -v
# Optional: run the storage contracts on a particular mounted filesystem.
# Only uniquely named temporary test directories are created and removed.
PHOTOFLOW_STORAGE_TEST_ROOT=/mnt/usb python3 -m unittest tests.test_storage -v
```

Tests use an in-memory filesystem, explicit clock, sequential IDs, and fixture
metadata reader. The same filesystem contracts run against real temporary
directories. Failure injection covers move-journal boundaries, recovery
conflicts, queue sealing, caching, metadata provenance, collisions, and repairs.
Storage tests also cover competing creators and an actual subprocess exiting
immediately after its media move, before publishing the destination sidecar.

| Module | Responsibility |
| --- | --- |
| `model.py` | Records, validation, events' data shapes, path policy |
| `ports.py` | Filesystem, clock, ID, metadata-reader contracts |
| `runner.py` | Lock/recovery, inventory/reconciliation, sealed queue, persistence |
| `stages.py` | Ordered observation, extraction, matching, planning, execution |
| `metadata.py` | Source index, lossless import, provenance and resolution |
| `content.py` | Stable streaming hashes and byte comparison |
| `moves.py` | Persisted intent and idempotent recovery |
| `adapters.py` | Local filesystem, UTC clock, UUIDs, optional ExifTool |
| `cli.py` | Arguments, wiring, search, JSON reporting |

`Runner(..., stages=...)` accepts any ordered sequence of objects implementing
`run(batch, context)`. Begin with `default_stages()` and insert a collection-wide
similarity or enrichment stage before planning. Stages update the in-memory
records and use `context.complete`/`context.event`; the runner persists changes.
The tuple of work items stays fixed. New adapters can implement the small ports
without changing the domain rules.

Perceptual similarity and optional AI analysis are future layers. They must
record versioned, pairwise evidence, inspect images independently of exact-file
sizes, retain originals, and respect human overrides. This version does not
decode images, recognize faces, prune media, or provide a gallery. ZIP extraction
is a separate preparation step rather than part of the refinement pipeline.
