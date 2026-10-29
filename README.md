# PhotoFlow monorepo

Filesystem-first photo ingestion and a home for the photo-library web GUI.
The existing service preserves metadata, identifies exact duplicates, and
organizes media using portable JSON records.

```text
apps/
  photoflow/          Python service, tests, operational scripts, deployment
  web/                Reserved for the photo-library web GUI
PLAN.md               Architecture decisions and implementation roadmap
Makefile              Repository setup and validation commands
```

Each application owns its packaging and dependencies. Shared packages can be
introduced when there is code both applications actually use.

## Development

From the repository root, with Python 3.11 or newer:

```bash
make setup
make test
.venv/bin/photoflow --help
```

Without `make`, run the equivalent commands directly:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e apps/photoflow
python3 -m unittest discover -s apps/photoflow -t apps/photoflow -v
```

On Debian/Ubuntu, virtual environment creation requires `python3-venv`.

`make setup` creates `.venv` and installs the service in editable mode. Tests
also run without installation using `make test PYTHON=python3`.

See the [service guide](apps/photoflow/README.md) for scratch-library setup,
metadata, safe ingestion, storage requirements, access statistics, and
deployment. The installed `photoflow` command works from any directory.
For module execution without installation, first `cd apps/photoflow`.

## Applications

- [PhotoFlow service](apps/photoflow/README.md): working Python batch processor.
- [Web GUI specification](apps/web/spec/README.md): UI, API, storage, Linux login,
  thumbnails, background work, and first-release acceptance criteria.
- [Plan](PLAN.md): design decisions, completed validation, and follow-on work.

Photo libraries are runtime data outside this repository. Existing library
paths, record IDs, sidecar schemas, and installed CLI entry points are unchanged
by the repository reorganization.
