# PhotoFlow Web — first-release specification

Status: ready for implementation planning. These documents specify new work;
they do not claim the web application or the service extensions already exist.

Build a straightforward, responsive photo library: a fast timeline, a useful
viewer, actual folders, and dependable editing. Originals and portable metadata
live on the filesystem. The application should be useful on a phone and a desktop
without becoming a second archive format.

## Read in this order

1. [Product and scope](01-product.md): requirements, defaults, and boundaries.
2. [Screens and interactions](02-experience.md): navigation and complete flows.
3. [Storage and consistency](03-storage.md): authoritative data and mutations.
4. [Authentication and access](04-auth.md): Linux login and shared-library roles.
5. [Thumbnails and media](05-media.md): formats, caching, scheduling, and budgets.
6. [HTTP API](06-api.md): resource contracts, errors, concurrency, and examples.
7. [Jobs and operation](07-jobs.md): uploads, scanning, recovery, and deployment.
8. [Acceptance and delivery](08-delivery.md): TDD scenarios and release gates.

Requirement IDs in these documents are stable. MUST is required for the first
release; SHOULD permits a documented implementation tradeoff. Performance
numbers are acceptance targets to measure, not results already achieved.

## Architecture decisions

- [ADR 0002: Place hierarchies and offline geocoding](adr/0002-place-hierarchies-and-offline-geocoding.md)
  adds sourced coordinates, hierarchical Place filters and offline enrichment.

- [ADR 0001: Visual queries, saved views, and explicit batch targets](adr/0001-visual-querying-and-saved-views.md)
  specifies the filter sidebar, persistent personal views, query URLs, and reviewed
  batch operations. Its People Any/All and exact label-selection rules refine the
  original collection-search proposal.

## Decisions made for this specification

| Area | First-release decision |
| --- | --- |
| Library | One configured library per installation; existing PhotoFlow identity |
| Users | Linux username/password through PAM; explicit group-based web access |
| Visibility | Shared family library; every authorized reader sees the same library |
| Storage | Originals and portable JSON authoritative; disposable SQLite read catalog |
| UI | Timeline, folders, search, viewer, uploads, activity, trash, settings |
| Folder control | Full CRUD for user folders under `folders/`; system/source folders browsable |
| Photo updates | Metadata, placement, favorites, tags, and nondestructive rotation |
| Delete | Move to recoverable trash; explicit administrator purge, no automatic expiry |
| Thumbnails | 64/256/512/1024/2048-pixel bounds; progressive, cached, asynchronous |
| Scheduling | Explicit upload completion, debounced external changes, periodic reconciliation |
| Deployment | Same-origin web/API, HTTPS, unprivileged services on the Ubuntu host |
| Implementation baseline | React + TypeScript UI; Python HTTP API and workers importing PhotoFlow |

React with a Vite build and FastAPI are the proposed implementation baseline.
Pin maintained versions and decoder capabilities when implementation starts.
Avoid a separate remote queue service initially: durable filesystem jobs and a
single mutation coordinator fit this installation. A framework change must keep
these resource contracts and tests intact.

## Vital additions to basic CRUD

Recoverable trash, resumable uploads, bulk selection, search, conflict detection,
background-job visibility, storage-full handling, accessible mobile navigation,
and explicit permissions are part of the first release. Manual organization must
survive scans. Downloading originals must preserve bytes. A bad image must not
block other thumbnails. A missing USB volume must never create a replacement
library on the host disk.

No additional user decision blocks this specification. The shared-library access
model, `folders/` namespace, and manual trash retention are deliberate defaults;
private per-user libraries or arbitrary writable source folders would require a
separate scope change.
