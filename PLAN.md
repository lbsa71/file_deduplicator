# PhotoFlow implementation plan

This plan distills the *Fotohantering* conversation. Later decisions supersede
earlier sketches: one finite batch command, no database, adjacent JSON records,
and UUID filenames rather than original names or content-addressed paths.

## First useful service

Periodically scan a configured library, refine metadata, identify exact
duplicates, and move files into a convergent layout. The inbox is an ordinary
folder: every noncanonical path is eligible for placement. Keep the service
small enough to understand and extend without a workflow framework.

1. Require an initialized library marker, acquire a nonblocking exclusive lock,
   and recover pending operations before discovery.
2. Inventory media and managed records. Reconcile stale paths, including media
   moved separately from its sidecar. Require unique, verified evidence; report
   ambiguous associations, copied record IDs, and missing media without pruning.
3. Freeze the queue. Run each refinement stage over the entire batch before
   starting the next. Queue items retain their identity when their paths change.
4. Observe readiness; fingerprint content; import and resolve metadata; match
   duplicates; reserve destinations; execute journaled moves. Persist current
   state and audit history together through one coordinator.
5. Prune empty directories after a successful placement pass, emit a structured
   summary, and exit. Cron or a systemd timer supplies repetition.

## Data and policy

- A stable record UUID identifies an occurrence and its history; SHA-256
  identifies its verified bytes; a root-relative path is its current locator.
- Use `photos/YYYY/MM/<uuid>.<ext>` or `undated/<uuid>.<ext>`. Normalize the
  extension, retain every original filename and folder in source records, and
  search those names without turning camera filenames into descriptive tags.
- Keep imported JSON documents and unknown fields, resolved values with
  provenance, manual overrides, stage checkpoints, and an ordered event log in
  `<media>.photo.json`. Never rewrite original Takeout JSON.
- Import adjacent supplemental/legacy Takeout JSON and immediate-folder
  `metadata.json`. A folder or album name is distinct from a person label.
  Revisit original source locations so late metadata can enrich moved media.
  Preserve prior source-document revisions and conflicting assertions.
- Cache expensive work using content identity, processor version, relevant
  metadata inputs, and configuration. Audit timestamps and moves are not
  extraction inputs. Explicit verification bypasses stat-based hash caches.
- Use size → first 1 KiB → complete SHA-256 → byte comparison for exact matches.
  Every new file gets a full hash because safe placement and repair need it.
  Reconsider the whole batch each pass so new files match previously processed
  ones. Merge provenance, retain both records, and move duplicates to review;
  never delete a duplicate's bytes automatically.
- A quiet period is a readiness heuristic. Producers should upload temporary
  extensions and rename only after media and metadata are complete.

## Boundaries

Use Python 3.11+ and its standard library for the core. Inject filesystem,
clock, IDs, and embedded-metadata reader. Keep deterministic rules ordinary
functions. Provide an optional ExifTool adapter; it must not be required for
Takeout ingestion. Use a tuple of work items and a small stage protocol, with
one owner of persisted changes. Avoid a plugin registry or persistent queue.

Moves are same-filesystem, no-overwrite operations. Journal intent and the final
record before touching media; verify content during recovery; publish the
destination sidecar before removing the old one. Flush file and directory
entries. Keep unresolved operations for inspection and stop normal processing
until they are resolved. Dry runs write nothing, including locks or markers.

## Test-driven milestones

- [x] Inventory, sidecar creation, scan history, unchanged-pass caching.
- [x] Takeout people/album separation, unknown fields, late metadata, protected
      overrides, and preserved original-name aliases.
- [x] Full-batch exact sieve, provenance merging, new duplicates of old files,
      and same-prefix/different-tail counterexamples.
- [x] Convergent UUID placement, a sealed queue, collision protection, and
      deferral when files change during reads.
- [x] Reconciliation, malformed records, duplicate IDs, and ambiguous hashes.
- [x] Journal recovery at each interruption boundary; filesystem contracts
      against real temporary directories as well as an in-memory fake.
- [x] CLI, search, read-only preview, cron/systemd examples, and a documented
      end-to-end smoke test.

Write failing behavioral tests before their implementation. Run the complete
suite and a real-filesystem CLI exercise before considering the slice complete.

Validation completed: 43 standard-library tests, including six interrupted-move
boundaries, plus a scratch-library CLI exercise with real ExifTool 13.59 output.
The scratch exercise checked read-only preview, metadata-only processing,
duplicate review, capture offsets, alias search, full verification, and an
unchanged second pass with zero hashes, extractions, or moves. The systemd units
passed syntax verification with a temporary installed-executable substitution.

### exFAT support and real-data pilot

- [x] Replace Linux hard-link publication with `renameat2(RENAME_NOREPLACE)` for
      media moves and exclusive creation of markers, sidecars, and journals.
      Unsupported operations fail without a check-then-rename fallback.
- [x] Preserve replay of legacy link/unlink journals.
- [x] Test competing creators, existing-file/directory collisions, interruption
      boundaries, and a subprocess exiting after its media move. Run the same
      storage contracts on the actual exFAT USB drive.
- [x] Copy 64 original images (about 147 MB) from `/mnt/usb/Foton` into a separate
      pilot library, add one labelled duplicate control, and run preview,
      metadata-only processing, placement, rescan, and full verification with
      ExifTool. All 65 media hashes are preserved, source file inventory and
      sampled content hashes are unchanged, and every pass reports zero errors.
      The unchanged rescan performs zero hashes, extractions, or moves. The
      source ZIP archives were not part of that pilot.

The pilot is `/mnt/usb/Foton-managed-pilot-dblpihqj`; its summaries, source
inventory, and checksum evidence are in `.photoflow/pilot/`. The original
`Foton` tree has not been initialized or reorganized.

### Takeout extraction and metadata pilot

- [x] Add a separate, explicitly invoked extraction helper for the current
      25-part export. Validate paths, coordinate shared destinations, stream
      member CRC/size checks, re-read outputs for SHA-256 verification, and bind
      durable completion manifests to the ZIP and its directory membership.
      Delete only verified ZIPs when `--delete` is explicitly requested.
- [x] Test corrupt archives, duplicate/conflicting paths, path traversal,
      symlinks, modified completion records, and interrupted archive cleanup.
- [x] Complete the pipelined 25-part extraction under `/mnt/usb/tx`, removing
      each ZIP only after verified output and durable completion. Three workers
      own disjoint archive-number shards, share destination locks, and wait for
      finalized names while the Mac transfer continues. Progress is recorded in
      `.takeout-extract/summary.json` and per-archive completion manifests.
- [x] Use six real media files and their available JSON from verified archive
      001 in a new inbox pilot. Import a plain copy first, then its Takeout
      counterpart. Preserve the original record ID and both source occurrences;
      merge the real people labels, retain all six raw JSON documents and their
      unknown fields, and keep album context separate from people. Check all
      media hashes and a convergent unchanged rescan.

The real metadata pilot is `/mnt/usb/Foton-takeout-metadata-pilot-dpw8ek2t`, with
evidence in `.photoflow/pilot/report.json`. It covers JPEG, HEIC, MOV, and MP4;
four distinct people labels are preserved across seven media records (including
the intentional duplicate). The source samples remain unchanged.

The real export also contains numbered supplemental collision variants such as
`.supplemental-metadata(1).json`, including documents with people labels. They
remain preserved and reported as unmatched; an occurrence association must be
proved before their annotations are attached. The pilot uses unambiguous
standard-name pairs and does not claim full collision-variant coverage.

### Unified processing inbox

- [x] Preserve `/mnt/usb/Foton` and prepare a SHA-256-verified working copy:
      4,498 source files, 29,293,986,400 bytes. Source signatures and inventory
      remained unchanged during the copy.
- [x] Expand the 13 real ZIPs in that copy, preserving their internal paths and
      grouping the nine split Google Photos parts together. Verify all 4,468
      extracted entries (17,826,140,480 bytes) before removing working-copy ZIPs.
      Retain original ZIPs in the original Foton backup. Ignore Finder resource
      files that merely have `.zip` suffixes.
- [x] Publish the verified Foton copy and the complete new Takeout under
      `/mnt/usb/PhotoLibrary/inbox/{Foton,Takeout}` using no-overwrite directory
      renames. Persist publication intent and verify relocated paths and sizes.
      Preserve the extraction manifests and their new root mappings.

The new 25-part Takeout contains 32,631 verified file entries and
52,079,131,389 extracted bytes. The final proof is
`/mnt/usb/PhotoLibrary/.photoflow/preparation/consolidation.json`. New Takeout
manifests are rooted at `PhotoLibrary/inbox`; legacy manifests are rooted at
`PhotoLibrary/inbox/Foton`. Three existing incomplete `.partial` downloads are
retained without expansion. This prepared the combined inbox for the processing
pass described below.

Final validation: 83 repository tests, seven storage contracts on the actual
exFAT volume, two real-data ingestion pilots, verified extraction of all 38
archives, and checked directory publication.

### Full combined-collection pass

- [x] Seal and fingerprint all 24,283 supported media files before moving them.
      Save the record IDs, original paths, SHA-256 multiset, and byte totals as
      a baseline. Confirm a cached, read-only preview has unique destinations.
- [x] Batch optional ExifTool reads in groups of 64 dirty files, with signature
      checks and individual-read fallback. Persist metadata checkpoints after
      each group; test interrupted-pass reuse. Exclude reserved sidecar-write
      temporary names from enumeration.
- [x] Organize every media occurrence while retaining all duplicate bytes.
      The initial pass moved 24,145 files and safely deferred 138 whose observed
      filesystem information changed. The next pass rehashed changed signatures
      and moved all 138 without new metadata extraction or further deferrals.
- [x] Complete the final read-only rescan and compare every record against the
      sealed baseline, including paths, sizes, identities, duplicate keepers,
      source metadata, pending operations, and the untouched original backup.

The completed library contains 13,034 dated canonical files, 436 undated
canonical files, and 10,813 retained duplicate copies in review. All 24,283
record IDs and the complete SHA-256 multiset match the baseline, totaling
80,157,609,076 media bytes and 13,470 unique content hashes. There are no pending
operations or supported media remaining in the inbox. All 16,277 raw JSON files
and three incomplete downloads remain. Aggregated people labels appear on
10,088 records, with 30 distinct labels; 4,451 keepers retain source occurrences
from both Foton and the new Takeout.

The final read-only rescan processed every record with zero hashes, extractions,
move proposals, deferrals, or errors. All 89 repository tests pass. The original
Foton inventory remains 4,498 files; seven files with changed filesystem IDs or
other stat fields were rehashed and match their original SHA-256 values. Those
stat observations never substitute for a content check when they disagree.

Operational evidence is under
`/mnt/usb/PhotoLibrary/.photoflow/runs/full-collection/`. Unmatched imported JSON
is retained: 424 files are byte-identical to documents already embedded, 211
contain distinct unmatched metadata, and one is invalid JSON. Ambiguous
numbered variants remain separate rather than receiving guessed associations.

### Archiving and empty-directory cleanup

- [x] Move the three top-level `Foton*` trees to `/mnt/usb/Backup` with
      no-overwrite directory renames. Verify all 4,684 file paths, sizes, and
      modification times after relocation. Save the original-to-backup mapping
      in `.photoflow/preparation/foton-backup-relocation.json`.
- [x] Snapshot directory candidates before discovery and prune them bottom up
      after successful placement. Preserve the root, inbox, application state,
      nonempty directories, symlinks, other filesystems, and later arrivals.
      Use `rmdir` only, report removed paths, and skip failed, deferred, preview,
      and metadata-only passes. Cleanup errors are warnings.
- [x] Validate the filesystem ports on real and in-memory adapters, including
      a concurrent arrival between enumeration and removal. All 96 repository
      tests and seven storage contracts on the USB volume pass. A real exFAT
      scratch-library run removes only emptied directories and converges on
      the next pass without hashes, extraction, moves, or additional pruning.

The housekeeping pass checked all 24,283 library records with no errors or move
proposals, then removed nine genuinely empty directories. The complete file
inventory remained unchanged. Its report is
`.photoflow/runs/empty-directory-cleanup.json`; folders containing original JSON
or Finder metadata remain available.

### Incremental-run optimizations and access statistics

- [x] Write photo sidecars only for event/checkpoint changes. Routine scan and
      completion timestamps no longer force writes or serialization. Publish
      one `.photoflow/last-run.json` for successful writable passes; keep
      explicit per-file audit events available through `--audit-every-scan`.
- [x] Persist disposable source-JSON cache shards keyed by complete stat
      signatures, library/schema identity, and payload checksums. Recheck source
      stability, rebuild corrupt caches from originals, preserve revisions,
      and bypass caches under `--verify`. Previews write no state.
- [x] Collect file paths, directory candidates, and initial file signatures in
      one filesystem walk; reuse the initial signatures during discovery.
- [x] Add `--stats` for filesystem-port calls, categorized read opens and bytes,
      writes and payload sizes, inventory entries, cleanup attempts, and elapsed
      time. Keep physical-device and kernel-syscall claims outside these counts.
- [x] Use failing behavioral tests first, including unchanged byte-for-byte
      sidecars, cache invalidation/corruption, a source changing during a cache
      lookup, read-only behavior, combined scans, and counter accuracy. All 108
      repository tests and seven actual-USB storage contracts pass.

Two normal writable passes on `/mnt/usb/PhotoLibrary` processed all 24,283
records without errors, deferrals, extraction, or moves. The cache-building
pass took 104.41 seconds, refreshed 1,468 changed filesystem signatures, and
populated 256 shards. The following unchanged pass took 52.60 seconds and used
16,020 source-cache hits. It performed one inventory walk, no media-content
opens, hashes, sidecar writes, or cache-shard writes, and one 81,094-byte
successful-run report write. One existing empty, invalid JSON file was reopened
and retried; it contributes zero payload bytes and remains unmatched.

The unchanged pass read 24,283 sidecars (444,379,720 bytes) and 257 application
state files (22,042,836 bytes), issued 150,801 explicit stat calls and 257
existence calls, and attempted 6,343 empty-directory removals without removing
anything. The single inventory contained 65,036 files and 6,344 directories;
pending-state enumeration is separate. Counters exclude adapter-internal path
checks and physical device I/O. Verification confirmed an unchanged complete
file inventory, all record IDs/hashes/sizes matching the sealed baseline, and
zero pending operations. Reports are in `.photoflow/runs/optimizations/`.

## Follow-on layers

### Web service initial deployment

The initial web service is implemented and deployed under systemd, with an
unprivileged API, separate PAM broker and HTTPS nginx listener. See the
[web runbook and current limits](apps/web/README.md). It supports the core browsing,
upload/download, metadata editing, manual organization, folder operations,
trash/restore and rescan workflows. The complete web specification remains the
release target; not every acceptance gate or advanced job/cache feature is done.

Validation: 108 existing service tests, 12 web/storage/auth scenarios, actual
PAM positive/negative checks, a real authenticated HTTPS library/thumbnail/download
check, desktop/mobile Chromium smoke tests, and full real-PAM/API CRUD on a synthetic
exFAT scratch library. Live media was not used for
mutation tests. The library marker migrated to format 2 with its original backed
up so unsupported writers reject new placement/trash behavior.

Keep exact matches, alternate encodings, visually similar photos, and related
content as different relationships. Perceptual comparison must inspect all
images independently of the exact-size sieve, preserve pairwise evidence, and
record normalization/tool versions. Add it as a stage using a proven decoder
or tool; retain originals. Optional AI enrichment belongs behind a versioned
adapter and must not block ingestion or override human decisions. RAW/JPEG and
Live Photo relationships, XMP export, richer Takeout cross-part matching,
completed-batch manifests, cross-filesystem transfers, media retention/pruning, and a
review UI are later work, not hidden dependencies of this first service.

## Monorepo structure

- [x] Move the existing Python service, tests, extraction scripts, packaging, and
      deployment examples into `apps/photoflow/`, preserving Python imports and
      the installed `photoflow` command.
- [x] Add root setup/test commands and reserve `apps/web/` for the photo-library
      GUI. Each application owns its dependencies and deployment lifecycle.
- [x] Author the [web specification](apps/web/spec/README.md): timeline/folders,
      uploads/downloads, metadata CRUD, trash/restore, Linux/PAM roles, multilevel
      thumbnails, HTTP contracts, jobs, consistency, and TDD delivery gates.
- [ ] Implement the web application and its server API. Keep filesystem access
      on the server and route mutations through the existing coordinator and
      lock. Preserve sidecar metadata as the source of truth.
- [ ] Extract shared code into `packages/` only when both applications need it;
      choose the web framework when implementing the GUI.

Repository reorganization does not change the photo library layout or record
schema. The service guide is now `apps/photoflow/README.md`.
