"""One finite pass, a sealed queue, and one owner of record writes."""

import json
import math
from collections import Counter, defaultdict
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import PurePosixPath

from .content import fingerprint
from .model import MARKER, PENDING, SIDECAR, Record, Summary, WorkItem, encoded, input_key, protected_directory, timestamp
from .moves import MoveJournal
from .metadata import SourceCatalog
from .ports import BusyError, ChangedError

MEDIA_EXTENSIONS = frozenset(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif',
    '.avif', '.tif', '.tiff', '.bmp', '.dng', '.cr2', '.cr3', '.nef', '.arw', '.orf',
    '.rw2', '.raf', '.mov', '.mp4', '.m4v', '.avi', '.mkv', '.3gp', '.mts'))


@dataclass(frozen=True)
class Config:
    dry_run: bool = False
    move_files: bool = True
    verify: bool = False
    settle_seconds: float = 30
    audit_every_scan: bool = False
    duplicates: str = 'review'
    expected_library_id: str | None = None
    extensions: frozenset[str] = MEDIA_EXTENSIONS

    def __post_init__(self):
        if not math.isfinite(self.settle_seconds) or self.settle_seconds < 0 or self.duplicates not in ('keep', 'review'):
            raise ValueError('invalid settle period or duplicate policy')
        if '.json' in self.extensions:
            raise ValueError('JSON files are reserved for metadata and cannot be selected as media')


class Context:
    def __init__(self, fs, clock, ids, reader, config, summary, library_id, snapshot):
        self.fs, self.clock, self.ids, self.reader = fs, clock, ids, reader
        self.config, self.summary, self.library_id = config, summary, library_id
        self.inventory = frozenset(snapshot.files)
        self.observations = snapshot.signatures
        self.sources = SourceCatalog(fs, self.inventory, library_id, verify=config.verify, summary=summary)
        self.dirty = set()
        self.used_documents = set()
        self.reconciled_sidecars = {}
        self.moves = MoveJournal(fs, ids, library_id)
        self.pending_failure = False

    def event(self, record, event_type, **data):
        self.dirty.add(record.id)
        history = record.data['history']
        history.append({'seq': len(history) + 1, 'event_id': self.ids.new(),
                        'run_id': self.summary.run_id, 'at': timestamp(self.clock.now()),
                        'type': event_type, 'data': data})

    def complete(self, record, stage, key, result=None, version='v1'):
        checkpoint = {'input_key': key, 'version': version, 'completed_at': timestamp(self.clock.now())}
        if result is not None:
            checkpoint['result'] = result
        record.data['stages'][stage] = checkpoint
        self.event(record, 'stage_completed', stage=stage, input_key=key)

    def fail(self, item, error):
        item.blocked = True
        if isinstance(error, ChangedError):
            self.summary.deferred += 1
            self.summary.warnings.append(str(error))
            self.event(item.record, 'deferred', reason=str(error))
        else:
            self.summary.errors.append(f'{item.path}: {error}')
            self.event(item.record, 'processing_failed', reason=str(error))

    def persist(self, item):
        if self.config.dry_run:
            return
        target = item.path + SIDECAR
        if item.saved is not None and item.sidecar_path == target and item.record.id not in self.dirty:
            return
        raw = item.record.to_bytes()
        if item.sidecar_path != target:
            item.record = self.moves.prepare(item.record, item.path, item.path, item.sidecar_path)
            item.sidecar_path = target
            item.saved = item.record.to_bytes()
        elif raw != item.saved:
            exists = self.fs.exists(target)
            if exists:
                current = Record.parse(self.fs.read_bytes(target), self.library_id)
                if current.id != item.record.id:
                    raise ValueError(f'sidecar collision at {target}')
            self.fs.atomic_write(target, raw, replace=exists)
            item.saved = raw
        self.dirty.discard(item.record.id)


def discover(ctx):
    fs, inventory = ctx.fs, ctx.inventory
    candidates = {p for p in inventory if PurePosixPath(p).suffix.lower() in ctx.config.extensions}
    loaded, blocked = [], set()
    for path in sorted(inventory):
        if not path.endswith(SIDECAR):
            continue
        adjacent = path[:-len(SIDECAR)]
        if adjacent in inventory:
            candidates.add(adjacent)
        try:
            raw = fs.read_bytes(path)
            loaded.append((path, Record.parse(raw, ctx.library_id), raw))
        except (ValueError, OSError, TypeError) as error:
            ctx.summary.errors.append(f'{path}: {error}')
            blocked.add(adjacent)
    counts = Counter(record.id for _, record, _ in loaded)
    repeated = {record_id for record_id, count in counts.items() if count > 1}
    for record_id in sorted(repeated):
        ctx.summary.errors.append(f'duplicate record ID {record_id}; copied sidecars require inspection')
    assigned, items, orphans = set(), [], []

    def attach(sidecar, record, raw, media, verified=False):
        observed = ctx.observations[media]
        old = record.path
        if old != media or sidecar != media + SIDECAR:
            if not verified and (not record.sha or fingerprint(fs, media, observed)[0] != record.sha):
                raise ValueError(f'content conflict while reconciling {sidecar} with {media}')
            record.path = media
            record.file['fingerprint'] = observed.to_dict()
            ctx.event(record, 'location_reconciled', **{'from': old, 'to': media, 'old_sidecar': sidecar})
            if sidecar != media + SIDECAR:
                ctx.reconciled_sidecars[sidecar] = record.id
        assigned.add(media)
        items.append(WorkItem(record, observed, sidecar, raw))

    for sidecar, record, raw in loaded:
        adjacent = sidecar[:-len(SIDECAR)]
        if record.id in repeated:
            blocked.update((adjacent, record.path))
            continue
        if adjacent in candidates and adjacent not in blocked:
            try:
                attach(sidecar, record, raw, adjacent)
            except (ValueError, OSError, ChangedError) as error:
                ctx.summary.errors.append(str(error))
                blocked.add(adjacent)
        else:
            orphans.append((sidecar, record, raw))

    # Only orphan repair requires hashing unassociated files before normal stages.
    available = candidates - assigned - blocked
    by_hash = defaultdict(list)
    if orphans:
        for path in sorted(available):
            try:
                by_hash[fingerprint(fs, path)[0]].append(path)
            except (ValueError, OSError, ChangedError) as error:
                ctx.summary.errors.append(f'{path}: {error}')
                blocked.add(path)
    orphan_counts = Counter(record.sha for _, record, _ in orphans)
    for sidecar, record, raw in orphans:
        matches = by_hash.get(record.sha, []) if record.sha else []
        # A known locator can disambiguate a sidecar moved on its own. A media
        # relocation with several equal candidates cannot establish occurrence identity.
        if record.path in available and record.path in matches:
            matches = [record.path]
        if len(matches) == 1 and orphan_counts[record.sha] == 1:
            try:
                attach(sidecar, record, raw, matches[0], verified=True)
            except (ValueError, OSError, ChangedError) as error:
                ctx.summary.errors.append(str(error))
                blocked.update(matches)
        else:
            diagnosis = 'ambiguous_association' if matches else 'missing_managed_media'
            ctx.summary.errors.append(f'{diagnosis}: {sidecar}')
            blocked.update(matches)
            if record.path in candidates:
                blocked.add(record.path)
    for path in sorted(candidates - assigned - blocked):
        record = Record.create(ctx.ids.new(), ctx.library_id, path)
        if path.startswith('folders/'):
            record.data['placement'] = {'mode': 'manual', 'folder_path': str(PurePosixPath(path).parent)}
        ctx.event(record, 'discovered', path=path)
        items.append(WorkItem(record, ctx.observations[path], path + SIDECAR))
    return tuple(sorted(items, key=lambda item: item.path))


def prune_empty_directories(fs, candidates, summary):
    for path in sorted(candidates, key=lambda p: (p.count('/'), p), reverse=True):
        if path == 'inbox' or path == 'folders' or path.startswith('folders/') or protected_directory(path):
            continue
        try:
            if fs.remove_empty_directory(path):
                summary.removed_directories.append(path)
        except (OSError, ValueError) as error:
            summary.warnings.append(f'empty_directory_cleanup_failed: {path}: {error}')


class Runner:
    def __init__(self, fs, clock, ids, reader, config=None, stages=None, geocoder=None):
        self.fs, self.clock, self.ids, self.reader = fs, clock, ids, reader
        self.config = config or Config()
        self.geocoder = geocoder
        if stages is None:
            from .stages import default_stages
            stages = default_stages()
        self.stages = tuple(stages)

    def run(self):
        result = Summary(self.ids.new(), started_at=timestamp(self.clock.now()))
        try:
            if not self.fs.exists(MARKER):
                raise ValueError('library marker missing; initialize the intended library with photoflow init ROOT')
            marker = json.loads(self.fs.read_bytes(MARKER))
            if not isinstance(marker, dict) or marker.get('schema_version') not in (1, 2) or not isinstance(marker.get('library_id'), str):
                raise ValueError('invalid library marker')
            library_id = marker['library_id']
            if not library_id or (self.config.expected_library_id and self.config.expected_library_id != library_id):
                raise ValueError('library identity does not match the expected library')
            with nullcontext() if self.config.dry_run else self.fs.lock():
                if marker.get('schema_version') == 2 and not self.config.dry_run:
                    from .web_operations import recover
                    recover(self.fs)
                moves = MoveJournal(self.fs, self.ids, library_id)
                if self.config.dry_run:
                    if self.fs.list_files(PENDING):
                        raise ValueError('pending operations need recovery; run without --dry-run first')
                else:
                    if not self.config.move_files and self.fs.list_files(PENDING):
                        raise ValueError('pending operations need recovery; run without --no-move first')
                    result.recovered = moves.recover()
                snapshot = self.fs.inventory()
                directories = snapshot.directories if self.config.move_files and not self.config.dry_run else ()
                inventory = snapshot.files
                ctx = Context(self.fs, self.clock, self.ids, self.reader, self.config, result, library_id, snapshot)
                ctx.geocoder = self.geocoder
                batch = discover(ctx)
                result.discovered = len(batch)
                for stage in self.stages:
                    stage.run(batch, ctx)
                    if ctx.pending_failure:
                        return result
                    for item in batch:
                        ctx.persist(item)
                for item in batch:
                    if not item.blocked:
                        result.processed += 1
                        key = input_key([item.record.sha, item.path, item.record.data['resolved'],
                            item.record.data.get('duplicate_of'),
                            {name: checkpoint['input_key'] for name, checkpoint in item.record.data['stages'].items()
                             if name != 'processing'}])
                        if item.record.data['stages'].get('processing', {}).get('input_key') != key:
                            ctx.complete(item.record, 'processing', key)
                            ctx.event(item.record, 'processed', path=item.path, sha256=item.record.sha)
                        item.record.data['last_processed_at'] = timestamp(self.clock.now())
                        ctx.persist(item)
                known = {d['relative_path'] for item in batch for s in item.record.data['sources'] for d in s['documents']}
                for path in sorted(set(inventory) - known - ctx.used_documents):
                    if path.endswith('.json') and not path.endswith(SIDECAR):
                        result.warnings.append(f'unmatched_source_metadata: {path}')
                if not result.errors and not result.deferred:
                    prune_empty_directories(self.fs, directories, result)
                result.completed_at = timestamp(self.clock.now())
                if not self.config.dry_run and not result.errors and not result.deferred:
                    ctx.sources.save()
                    self.fs.atomic_write('.photoflow/last-run.json', encoded(result.to_dict()))
        except BusyError:
            result.locked = True
        except (OSError, ValueError, ChangedError, TypeError, KeyError) as error:
            result.errors.append(str(error))
        if result.completed_at is None:
            result.completed_at = timestamp(self.clock.now())
        return result
