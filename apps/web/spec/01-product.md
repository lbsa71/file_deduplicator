# Product and scope

## First-release requirements

| ID | Requirement |
| --- | --- |
| AUTH-01 | Authenticate Linux accounts and enforce reader/editor/admin roles on every resource |
| BROWSE-01 | Fast, paginated timeline with thumbnails, dates, favorites, and search |
| BROWSE-02 | Browse real folders, breadcrumbs, direct children, and optional recursive contents |
| PHOTO-01 | Upload one/many originals, resume interrupted transfers, preserve original filenames |
| PHOTO-02 | View photos, basic playable videos, metadata, sources, and duplicate relationships |
| PHOTO-03 | Download individual originals or a selected batch, optionally with portable metadata |
| PHOTO-04 | Move selected records, rotate their display, trash, restore, and explicitly purge |
| FOLDER-01 | Create, rename, move, and trash user folders; preserve intentionally empty folders |
| META-01 | Read/edit/reset supported metadata with provenance and concurrent-edit protection |
| JOB-01 | Request normal scans, metadata refresh, integrity verification, and thumbnail rebuild |
| MEDIA-01 | Multilevel thumbnails with responsive image selection and bounded background work |
| OPS-01 | Durable operations, progress/errors/retry, mount checks, and useful access statistics |
| UX-01 | Responsive layout, keyboard navigation, accessible controls, clear empty/error states |

## Meaning of a photo

A record identifies one physical media occurrence, including videos and retained
duplicates. The normal timeline shows active canonical records; it displays a
duplicate-count badge and a filter to include all occurrences. The folder view
shows the actual occurrences in that folder, regardless of canonical status.
Every destructive or bulk operation names the exact affected record IDs and count.
An action on a canonical record does not implicitly act on all duplicates.

Default sort is capture date descending, then record ID as a deterministic tie
breaker. Unknown dates appear in a separate Undated group. Date-only and
timezone-unknown values keep their precision; never silently convert an unknown
timezone to the server's timezone. A viewer opened from a search navigates that
search's ordering and returns to the same scroll position.

## Actual folders and logical albums

Folders represent filesystem directories. Albums are metadata labels that may
apply to a photo in any directory. Moving a photo does not change its albums or
people. Changing an album does not move a photo.

The root, `inbox`, `photos`, `undated`, `review`, application state, and imported
source directories have service-defined roles. Users may browse ordinary source
and generated folders but cannot rename or trash those trees in v1. UI-created
folders live beneath `folders/` and support full CRUD. Photos can be moved from
generated locations into these folders and retain their UUID filenames. This
restriction is visible through capabilities and explanatory disabled actions.

Empty user folders persist. Folder uploads may preserve a selected directory
structure inside a user folder. A normal timeline upload instead uses automatic
date placement. `folders/` is a normal part of the library scan, not a separate
collection.

## Metadata covered by CRUD

Supported editable fields: title, description, capture time, people, albums,
tags, favorite, location, and display rotation. Record IDs, content hashes, source
documents, original filename observations, and audit history are read-only.

Removing a field's override means “use imported information again.” Clearing its
value means “keep this empty,” even after rescans. The UI exposes both actions.
Original filenames remain searchable aliases. Person names are photo-level
labels; this release does not assert face locations or perform face recognition.

Bulk edits support adding/removing people, albums, and tags, setting favorites,
moving, trashing, and downloading. Scalar date/location edits are single-photo
operations initially to avoid accidental mass replacement. Bulk removal of an
imported label writes an explicit override, so rescanning cannot restore it.

## Out of scope

Public sharing, external identity providers, self-registration, Linux account
management, per-photo private permissions, AI classification, face recognition,
editing original pixels, replacing an existing original in place, video
transcoding, RAW development, and automatic duplicate deletion are later work.
Logical album labels are editable and filterable; a separate album object with
cover art, sharing, and album-level CRUD is later work. ZIP files are not unpacked
by browser upload in v1; the existing verified extraction tool remains separate.

HEIC/RAW/video originals remain uploadable and downloadable even when a preview
decoder is unavailable. Capability checks and placeholders explain this state.
