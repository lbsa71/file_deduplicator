# Thumbnails, previews, and original delivery

## Size ladder and rendering

MEDIA-01 defines these maximum dimensions (longest edge, no enlargement):

| Level | Purpose | Generation |
| --- | --- | --- |
| 64 | Tiny progressive placeholder | After ingestion |
| 256 | Small grid/mobile | After ingestion |
| 512 | Dense/high-DPR grid | After ingestion |
| 1024 | Viewer preview | On demand, then cache |
| 2048 | Large/high-DPR viewer | On demand, then cache |

Preserve aspect ratio; the UI chooses crop presentation. Use `srcset`/`sizes` and
actual viewport/DPR needs, cap grid requests at 512, reserve dimensions, and
virtualize offscreen rows. Never force all levels to exist before showing a photo.
Use WebP quality 80 for initial derivative recipes, with alpha preserved; add
formats only as separately keyed recipes. Report derivative bytes and visual
quality during validation. Originals remain available for full-resolution detail.

Use libvips through a replaceable renderer port. Its
[thumbnail operation](https://www.libvips.org/API/8.17/ctor.Image.thumbnail.html)
supports shrink-on-load; start from the source loader rather than decoding every
full-size image before resizing. Generate the small ladder in one worker job
where possible. Apply EXIF orientation, then display rotation; convert supported
profiles to sRGB, preserving alpha. Strip source EXIF/GPS from derivatives.
Version the exact orientation, color, animation-frame, and quality recipe.

## Formats

JPEG, PNG, WebP, GIF first frame, TIFF first page, and HEIC still images must have
real fixture coverage. HEIC support is a required deployment capability because
the existing library contains it. Probe the installed decoder build before
enabling the service; expose format capabilities in status. For AVIF/BMP and
other accepted image types, decode when supported or show a typed placeholder.

RAW uses a suitable embedded preview when available, with orientation verified;
otherwise show a RAW placeholder and original download. Full RAW development is
out of scope. Animation and Live Photo pairing are not reconstructed in v1.
Decode failure never changes the media's existence or destroys its metadata.

MOV/MP4 and other accepted videos use a bounded ffmpeg adapter for posters and
duration/dimensions. Default poster time is `min(1 second, duration / 10)`, or the
first decodable frame when duration is unknown. Native browser-compatible content
plays via authenticated range requests. Unsupported codecs show “Preview only;
download original to play.” Video transcoding is a later feature.

## Cache and work scheduling

Cache key = SHA-256 of content hash + recipe version + display rotation + target
level + format/quality + color policy + video poster timestamp. Descriptive edits,
folder moves, and record IDs are excluded. Identical content with the same display
instructions shares bytes, but access is checked through each requested record.
Check current source identity before decoding and before publishing; stale results
are discarded. Never fall back to a same-path different-content derivative.

Store sharded derivatives outside the scanned library, preferably on SSD. Publish
atomically and coalesce jobs by cache key. Cache loss triggers regeneration, never
loss of metadata. Default maximum 20 GiB, configurable; evict least recently used
unreferenced/past-demand entries to 80% at the limit. Keep access bookkeeping in
the derived catalog, batched rather than writing on every image hit. Do not evict
in-progress artifacts. Stop new generation before the configured free-space floor.

Priority: open viewer, visible grid, next viewport, background warming. Default
two decoder workers; each has a 512 MiB memory limit, one bounded CPU allocation,
30-second image timeout / 60-second video timeout, 150-megapixel input policy,
and 16 MiB output limit. Oversized sources fail gracefully or use a bounded embedded
preview; they remain downloadable. Enforce limits in subprocesses, not just Python
timeouts. Disable decoder network access and avoid shell command construction.

Cache misses enqueue work and return a pending response. They never decode inside
an HTTP request. Failed/unsupported states are cached by source and recipe revision;
scrolling does not continually retry a corrupt original. Explicit retry or a
changed recipe/source can retry. Default three attempts only for transient errors.

## HTTP delivery

Expose `pending`, `ready`, `failed`, and `unsupported` per variant. Pending API
responses include `Retry-After`; the UI uses job events or bounded polling and a
placeholder. Serve authorized bytes with ETags and `Cache-Control: private,
no-cache` so cache reuse revalidates access. No unauthenticated static media mount.

Original downloads are byte-identical, streamed with bounded memory. Support HEAD,
single byte ranges, `If-Range`, and safe Content-Disposition filenames. Never
transcode or rotate an “original” download. Optional sidecar/metadata export is a
separate choice. Follow [HTTP range and conditional request semantics](https://www.rfc-editor.org/rfc/rfc9110.html).

## Measured budgets

Use the existing 24,283-record / 13,470-unique-content library as the scale target.
Record CPU, RAM, SSD/USB models, decoder versions, client/browser, LAN speed, and
concurrency with every report. Separate cold generation from warm delivery.

| Scenario | Acceptance target |
| --- | --- |
| Warm listing/search, first 100 records | p95 ≤250 ms server time; zero library walks/media opens |
| Warm thumbnail response | p95 ≤100 ms server time; zero original reads/decodes |
| First viewport, 60 cached thumbnails | Usable ≤1.5 s on the documented LAN/client |
| Cold representative JPEG grid thumbnail | p95 ≤2 s with one interactive request and background load |
| Two clients request one missing variant | One generation job; both eventually receive it |
| Rename or people-label edit | Zero derivative regeneration |

Measure at least 100 requests for latency percentiles. Report HEIC, RAW, and video
generation separately with queue wait and decode time; never hide them in a JPEG
average. Track cache hits/misses/evictions, source bytes read, queue depth, decoder
time/failures/peak memory, and cache space. If the host misses a budget, document
the measured bottleneck and revise capacity explicitly before release.
