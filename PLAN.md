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
5. Emit a structured summary and exit. Cron or a systemd timer supplies repetition.

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
retained without expansion. The combined inbox is prepared for a subsequent
processing pass; it has not been reorganized into UUID paths.

Final validation: 83 repository tests, seven storage contracts on the actual
exFAT volume, two real-data ingestion pilots, verified extraction of all 38
archives, and checked directory publication.

## Follow-on layers

Keep exact matches, alternate encodings, visually similar photos, and related
content as different relationships. Perceptual comparison must inspect all
images independently of the exact-size sieve, preserve pairwise evidence, and
record normalization/tool versions. Add it as a stage using a proven decoder
or tool; retain originals. Optional AI enrichment belongs behind a versioned
adapter and must not block ingestion or override human decisions. RAW/JPEG and
Live Photo relationships, XMP export, richer Takeout cross-part matching,
completed-batch manifests, cross-filesystem transfers, retention/pruning, and a
review UI are later work, not hidden dependencies of this first service.
