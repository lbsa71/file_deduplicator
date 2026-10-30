# Screens and interactions

## Application shell

Desktop: left navigation, top search/upload area, central collection, optional
right detail panel. Navigation: Photos, Folders, Favorites, Duplicates, Trash,
Activity. Settings is available to administrators; account/logout to everyone.
Mobile: compact navigation drawer, search, upload button, full-screen viewer and
details sheet. Controls must remain usable at a 360 CSS-pixel viewport.

Use a restrained visual design with image content taking most of the space.
Timeline tiles preserve aspect ratio in justified rows with stable dimensions;
folder tiles include names and counts. Virtualize long collections. Skeletons
reserve space, and a thumbnail failure uses a stable placeholder rather than
collapsing the grid. Never request full originals to populate a grid.

Routes: `/login`, `/photos`, `/folders?path=...`, `/favorites`, `/duplicates`,
`/trash`, `/activity`, `/settings`, and `/photos/:recordId`. Filters and sort live
in URL parameters. A reload/deep link works after login. Validate the login return
URL as same-origin. Unauthorized routes reveal no counts, filenames, or images.

Canonical folder links also support `/folders/<root-relative-path>`, for example
`/folders/photos/2000/09`; the query-form route remains supported. Photo URLs use
the stable record ID and retain collection context when opened from a folder or
search. Closing the viewer returns to that context.

## Collection and selection

Search title, description, original filename aliases, people, albums, tags, and
current relative path. Filters: capture-date range, person, album, media type,
favorite, duplicate inclusion, and folder. Combine filters with AND; multiple
values within a filter use OR. Search and label matching are Unicode-normalized
and case-insensitive. Original spelling stays available for display.

Show loaded count and result count. A select control enters selection mode;
Shift-click selects a loaded range. “Select all results” captures a server-side
selection snapshot, with an explicit count, rather than silently selecting only
the current page. Selection snapshots expire after 30 minutes. New arrivals do
not join an existing selection. Bulk toolbar: Download, Move, Edit labels,
Favorite, Trash. Confirm trash using the actual count; show partial failures.

## Viewer

Open quickly using the best cached thumbnail, then sharpen to the viewport/DPR
appropriate preview. Left/right keys navigate; Escape closes; touch supports
swipe. Zoom and pan are supported for still images. Request an original only on
explicit original/download action. Show title or a useful original filename,
capture date, video duration, favorite, download, move, rotate, and more actions.

Details show editable metadata, current folder, original filenames, dimensions,
file type/size, people/albums/tags, and provenance. Advanced details expose
read-only raw source JSON, extraction status, duplicate links, and audit history.
Distinguish imported, user-overridden, and unknown values. Label canonical and
retained duplicate occurrences clearly. User-entered text is always text, never
interpreted HTML. No map request to a third party is required to view coordinates.

## Upload flow

Upload button, drag/drop, and supported browser folder selection share one
queue. Folder selection has an ordinary file-picker fallback. Display the target
folder, automatic/manual placement, file count, total bytes, and per-file status.
Accept associated Takeout JSON and folder `metadata.json` together with media.
Retain relative directory structure for matching; do not flatten collisions.

States: queued → uploading → uploaded → processing → ready; paused, failed, and
cancelled are explicit alternatives. Byte progress and processing progress are
separate. Retrying uses the existing upload identity. Browser reload can resume
after reselecting the same file and validating its identity; browser file handles
must not be assumed to survive. Leaving the page does not cancel committed work.

Successful transfer makes the file eligible for ingestion; it does not claim
metadata or thumbnails are finished. Processing placeholders may appear in the
grid and Activity. A small original should become browsable without waiting for
an entire large batch. Late source JSON enriches already committed occurrences.

## Folder flow

Breadcrumbs and children show directories separately from media. Users can
toggle direct children/recursive view. Create folder requires a validated name;
rename and move show the resulting path and affected count before execution.
Moving into a descendant or an occupied equivalent name fails without merging.
Move photos selects an existing user folder or creates one. “Use automatic
organization” removes a placement override and previews the proposed target.

Folder deletion means trash the registered user folder and its contents as one
recoverable operation. The dialog includes unrecognized/hidden file counts and
bytes; all are retained. Restore returns the entire operation. Existing target
conflicts offer another user-folder destination and never overwrite files.

## Editing, errors, and feedback

An edit form keeps a local draft until Save. On a revision conflict, keep the
draft, show the latest values, and allow a deliberate retry. Never silently
overwrite another person's edits. Moving/rotating/trashing shows a pending job
state, then refreshes affected records. Undo for trash submits a restore operation.

Activity shows uploads, scans, thumbnail backlog, bulk edits, and errors with
timestamps and retry controls. Display the last successful scan and index age.
Unavailable media uses “Storage unavailable” or “File missing” as appropriate;
metadata cached before a disconnect may still be browsed with a stale-data banner.
Low-space or unavailable-volume conditions disable affected writes and explain
the reason. Errors must have an actionable message and request/job reference.

## Accessibility

All flows work without drag/drop or a mouse. Visible focus, labelled buttons,
announced upload/error status, focus trapping/restoration in dialogs, reduced
motion, and adequate text/control contrast are acceptance requirements. Thumbnail
alt text uses title/description when present and a concise filename fallback.
Do not duplicate a full list of people into every image's accessible name.
