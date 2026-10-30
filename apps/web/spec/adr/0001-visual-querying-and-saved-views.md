# ADR 0001: Visual queries, saved views, and explicit batch targets

Status: Accepted — 2026-10-30

## Context

The library contains overlapping people, album memberships, dates, and tags.
Users need to explore those dimensions in any order, return to useful selections,
and perform metadata maintenance across many photos. A recursive virtual folder
tree expresses progressive intersection well, but becomes cumbersome for OR,
date ranges, changing an earlier constraint, and checking batch-operation scope.

## Decision

Use parallel, coordinated filter panels beside the thumbnail grid. Start with
People, Time, and Favourite; expose Albums, Tags, media type, and missing metadata
in compact expandable sections. Retain real filesystem folder navigation. A saved
view is a named live query, independent of imported album membership and physical
placement. New matching photos automatically appear in a saved view.

Use the existing React/Vite application, native labelled HTML controls, and Radix
Slider for the two-handle date range. Native date inputs are an equally capable
alternative to dragging. Do not introduce a dashboard framework or a second
complete navigation interface. A future tree can share this query model.

### Query semantics

- Different dimensions combine with AND. People explicitly offers Any selected
  (OR, default) and All selected (AND). Albums and tags use OR within their facet.
- Favourite offers Any / Yes / No. Date offers Any / Known / Unknown, inclusive
  start/end calendar dates, year shortcuts, and a year histogram. Photo capture
  dates use their recorded calendar date; choosing a range excludes undated items.
- Match complete label values, never substring matches. Preserve displayed labels.
  The existing text search remains separate and searches names and metadata.
- Counts are distinct photo occurrences in the same visibility/duplicate scope as
  the grid. OR facets count alternatives with their own selections omitted. All
  People counts preview intersection with the selected people. Histogram buckets
  omit the date constraint while retaining other dimensions.
- Keep selected zero-count values visible. Keep label order stable while counts
  change. Do not imply that overlapping person/album counts sum to the total.
- Missing people means missing labels, not absence of humans in an image.

### Interaction and persistence

On desktop filters remain visible alongside results. On narrow screens they
collapse into a labelled disclosure. Search within long label lists. Show active
filter chips and Clear filters above results. Changing filters resets pagination
and selection; changing pages preserves explicit selection. Keep controls mounted
and retain focus while results load. Ignore stale HTTP responses.

Checkbox changes update immediately; date-slider dragging stays local until
commit. Exact date fields and keyboard controls remain available. Browser history,
reload, viewer links, and login return retain the complete query. URLs expose
repeated `person`, `album`, `tag`, plus `people_mode`, `from`, `to`, `date`,
`favorite`, `type`, and `missing` parameters. Equivalent queries serialize in a
stable order. The API uses the same validated filter object with the current
text/folder/trash/duplicate scope.

Ordinary collection routes imply their scope (`/favorites`, `/trash`, or a folder
path). API-created saved queries may combine these scopes. Preserve any additional
constraints using `scope_folder`, `scope_duplicates`, `scope_favorite`, and
`scope_trash` URL parameters; flags accept only explicit `true` or `false`.
For example, `/trash?scope_favorite=true&favorite=no` deliberately matches nothing:
the favourite scope and the contrary metadata predicate both remain intact.
Folder `.` means all physical occurrences at the library root and survives saved
view round trips. Extra scope stays visible, survives photo links, and is cleared
when choosing a different collection from the main navigation. Normal UI queries
retain their existing concise URLs.

Saved views support create, open, update, rename, and delete. Store them per Linux
account in `.photoflow/views/` with library identity and optimistic revisions.
These files are authoritative user intent and must be backed up. A catalog rebuild
must not erase them. Query URLs remain independently copyable to another authorized
library reader; saving a view does not grant library access.

### Selection and batch work

Filtering chooses the working set; checkboxes choose action targets. Show both
counts. Offer Select page, Select all matching, and Clear selection. Select all
matching captures IDs and revisions server-side, including unloaded pages, for
30 minutes. Later arrivals cannot enter that selection. Explicit selections also
retain their observed revisions rather than silently fetching fresh revisions.

Before mutation, capture a one-shot plan with target count and representative
before/after metadata. A native modal dialog provides focus containment and a
clear Apply to N photos button. Add, Remove, Replace, and Reset to imported values
are separate operations. Set/clear favourites, date correction, move, trash, and
restore use the same selection and preview machinery. Imported raw JSON stays
unchanged; edits write manual overrides and audit events through the coordinator.

Validate the entire requested operation before the first mutation. Check each
record's revision at execution, skip conflicts, and report individual outcomes.
Never reevaluate a saved query or broaden a selection during execution. Plans are
claimed once; resubmission cannot silently repeat a partial operation. Persistent
job results show successes, conflicts, and errors. Recovery/retry requires a new
selection and preview when the original job was interrupted.

Downloads retain the existing export limits and make those limits visible. Admin
maintenance exposes the existing reconcile, verify, metadata, catalog, and
thumbnail scan modes with their whole-library scope clearly labelled. Targeted
decoder repair, date-offset bulk correction, persistent thumbnail failure facets,
and automatic replay of interrupted batches are follow-up work, not implicit
capabilities of a generic metadata edit.

### Storage and performance

Query a rebuildable SQLite projection with indexed label memberships. Facets and
matching IDs must not traverse the filesystem, read sidecars, or open originals.
Refresh projections when records change. Do not precompute every facet combination.
Use bounded listing pages and lazy thumbnails; fetch facet values separately from
the photos. Measure representative warm queries on the real library before
declaring latency targets met.

Use SQLite's rollback journal on the current deployment. The host runtime and the
available bundled Python wheel predate the upstream WAL-reset fix; introducing
WAL is deferred until a patched runtime is available. Catalog rebuilds publish
and prune in batches of 64 records, committing all projections of each record
together. Readers can run between batches rather than wait for the entire scan.
Browsing during a scan sees an incrementally refreshed committed catalog, not an
atomic snapshot of the whole scan. A read may briefly wait for the current batch;
the batch size is not a wall-clock latency guarantee. Frozen action selections
still retain their own explicit IDs and revisions.

## Alternatives and consequences

A dynamic folder tree remains attractive for progressive discovery, but repeats
dimensions, hides earlier constraints, and needs additional UI for ranges/unions.
Building both now doubles interaction/testing work. Parallel panels expose the
query and make maintenance scope easier to inspect. Their cost is screen space;
collapsible secondary groups and a responsive layout keep photographs prominent.

Radix supplies the difficult slider keyboard/focus interaction. Native checkboxes,
selects, date inputs, and dialogs keep dependencies small. No chart package is
needed for a small year histogram. Saved queries and folder/album labels remain
different objects because deleting a shortcut must not change image metadata.

## Acceptance

Tests cover Any/All people, exact label matching and special characters, OR
alternative counts, inclusive date boundaries, undated photos, stable URL round
trips, selected values with zero results, scope consistency, and no filesystem
reads during queries. Saved views survive rebuilds and enforce owner/revision
checks. Selection tests span multiple pages, later arrivals, concurrent edits,
invalid operations, replay, and partial failures. Browser tests cover filter
controls, deep links/reload/Back, keyboard date input, saved-view CRUD, explicit
selection, batch preview/application, and narrow-screen layout using scratch data.

## References

- [Flamenco: Faceted Metadata for Image Search and Browsing](https://courses.ischool.berkeley.edu/i247/f05/readings/Yee_Flamenco_CHI03.pdf)
- [Nielsen Norman Group: User Intent Affects Filter Design](https://www.nngroup.com/articles/applying-filters/)
- [WAI-ARIA: Multi-thumb Slider Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/slider-multithumb/)
- [Radix Slider: keyboard support and controlled ranges](https://www.radix-ui.com/primitives/docs/components/slider)
- [SQLite WAL concurrency and the WAL-reset fix](https://www.sqlite.org/wal.html#walresetbug)
