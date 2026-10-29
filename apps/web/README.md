# Photo-library web GUI

This directory is reserved for the web application. The GUI and its framework
are not implemented yet. Its dependencies, tests, and deployment configuration
will live here independently of the Python ingestion service.

The initial GUI should browse library records and their aggregated dates,
people, albums, descriptions, and original filenames, including retained
duplicate relationships.

Integration boundaries:

- Serve library records and media through a server API; the browser does not
  receive unrestricted filesystem access.
- Configure the library root at deployment time rather than committing media
  or machine-specific paths to this repository.
- Use stable record IDs for links and look up their current relative paths.
- Route metadata edits and processing requests through the PhotoFlow
  coordinator and its existing library lock.
- Preserve sourced metadata, explicit human overrides, and audit history.

The Python service can be installed from `../photoflow`; a Python API server
can import its existing `photoflow` package. If a different server runtime is
chosen, expose an explicit API rather than duplicating filesystem mutation
logic. Extract shared packages only when needed.

See the [repository plan](../../PLAN.md) and [service guide](../photoflow/README.md).
