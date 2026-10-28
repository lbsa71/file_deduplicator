"""Ordered batch stages. They change in-memory records; the runner persists them."""

import copy
import unicodedata
from collections import defaultdict

from .content import fingerprint, same_bytes, stable
from .metadata import RESOLVER_VERSION, import_sources, merge_sources, resolution_key, resolve
from .model import SIDECAR, destination, input_key, timestamp
from .ports import ChangedError


class ItemStage:
    def run(self, batch, ctx):
        for item in batch:
            if not item.blocked:
                try:
                    self.process(item, ctx)
                except (ValueError, OSError, ChangedError) as error:
                    ctx.fail(item, error)
                    if ctx.fs.list_files('.photoflow/pending'):
                        ctx.pending_failure = True
                        return


class Observe(ItemStage):
    def process(self, item, ctx):
        stable(ctx.fs, item.path, item.observed)
        record = item.record
        record.data['last_scanned_at'] = timestamp(ctx.clock.now())
        if ctx.config.audit_every_scan or record.file.get('fingerprint') is None:
            ctx.event(record, 'scanned', path=item.path, fingerprint=item.observed.to_dict())
        age = ctx.clock.now().timestamp() - item.observed.mtime_ns / 1_000_000_000
        if age < ctx.config.settle_seconds:
            raise ChangedError(f'waiting for quiet period: {item.path}')


class Fingerprint(ItemStage):
    def process(self, item, ctx):
        record = item.record
        stable(ctx.fs, item.path, item.observed)
        if (not ctx.config.verify and record.sha
                and record.file.get('sample_sha256')
                and record.file.get('fingerprint') == item.observed.to_dict()):
            return
        old_sha = record.sha
        sha, sample = fingerprint(ctx.fs, item.path, item.observed)
        record.file.update(sha256=sha, sample_sha256=sample, size_bytes=item.observed.size,
                           fingerprint=item.observed.to_dict())
        ctx.summary.hashed += 1
        ctx.event(record, 'content_changed' if old_sha and old_sha != sha else 'content_verified',
                  previous_sha256=old_sha, sha256=sha)
        if old_sha != sha:
            record.data.pop('duplicate_of', None)


class ExtractMetadata(ItemStage):
    def process(self, item, ctx):
        record = item.record
        stable(ctx.fs, item.path, item.observed)
        changed, used = import_sources(record, ctx.sources)
        ctx.used_documents.update(used)
        key = input_key([record.sha, ctx.reader.version])
        checkpoint = record.data['stages'].get('embedded_metadata', {})
        if checkpoint.get('input_key') != key:
            result = ctx.reader.read(item.path)
            stable(ctx.fs, item.path, item.observed)
            if not isinstance(result, dict):
                raise ValueError('metadata reader must return an object')
            ctx.complete(record, 'embedded_metadata', key, result, version=ctx.reader.version)
            ctx.summary.metadata_extracted += 1
        if changed:
            ctx.event(record, 'metadata_imported', source_count=len(record.data['sources']))
        refine(record, ctx)
        stable(ctx.fs, item.path, item.observed)


def refine(record, ctx):
    key = resolution_key(record)
    if record.data['stages'].get('resolved_metadata', {}).get('input_key') != key:
        old = record.data['resolved']
        resolved = resolve(record)
        changes = {field: {'from': old.get(field), 'to': value}
                   for field, value in resolved.items()
                   if field != 'provenance' and old.get(field) != value}
        record.data['resolved'] = resolved
        ctx.complete(record, 'resolved_metadata', key, version=RESOLVER_VERSION)
        ctx.event(record, 'metadata_enriched', resolver=RESOLVER_VERSION, changes=changes)


class ExactDuplicates:
    def run(self, batch, ctx):
        active = [item for item in batch if not item.blocked]
        by_id = {item.record.id: item for item in active}
        for item in active:
            relation = item.record.data.get('duplicate_of')
            if relation and relation['record_id'] in by_id:
                keeper = by_id[relation['record_id']]
                if item.record.sha != keeper.record.sha:
                    item.record.data.pop('duplicate_of')
                    ctx.event(item.record, 'relationship_invalidated', reason='content changed')
        groups = defaultdict(list)
        for item in active:
            record = item.record
            # Each successive part is a sieve; only complete bytes confirm equality.
            groups[(item.observed.size, record.file['sample_sha256'], record.sha)].append(item)
        for group in groups.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda item: (bool(item.record.data.get('duplicate_of')),
                'last_processed_at' not in item.record.data,
                item.path != destination(item.record, 'keep'), item.path))
            keeper = group[0]
            for item in group[1:]:
                relation = {'record_id': keeper.record.id, 'sha256': keeper.record.sha}
                try:
                    stable(ctx.fs, keeper.path, keeper.observed)
                    stable(ctx.fs, item.path, item.observed)
                    if item.record.data.get('duplicate_of') != relation:
                        if not same_bytes(ctx.fs, keeper.path, item.path):
                            raise ValueError('full-hash match failed byte comparison')
                        item.record.data['duplicate_of'] = relation
                        ctx.event(item.record, 'duplicate_identified', **relation)
                        ctx.event(keeper.record, 'duplicate_identified', record_id=item.record.id,
                                  sha256=keeper.record.sha)
                        ctx.summary.duplicates += 1
                    if merge_sources(keeper.record, item.record):
                        ctx.event(keeper.record, 'sources_merged', from_record_id=item.record.id)
                        refine(keeper.record, ctx)
                except (ValueError, OSError, ChangedError) as error:
                    ctx.fail(item, error)
                    if isinstance(error, ChangedError):
                        ctx.fail(keeper, error)
                        break


def collision_key(path):
    return unicodedata.normalize('NFC', path).casefold()


class PlanLocations:
    def run(self, batch, ctx):
        reserved = {}
        conflicts = set()
        inventory = defaultdict(set)
        for path in ctx.inventory:
            inventory[collision_key(path)].add(path)
        for item in batch:
            if item.blocked:
                continue
            try:
                target = destination(item.record, ctx.config.duplicates)
                key = collision_key(target)
                occupied = {p for p in inventory[key] - {item.path} if ctx.fs.exists(p)}
                sidecars = {p for p in inventory[collision_key(target + SIDECAR)] - {item.sidecar_path}
                            if ctx.fs.exists(p) and ctx.reconciled_sidecars.get(p) != item.record.id}
                if occupied or sidecars or key in reserved:
                    conflicts.update(occupied)
                    conflicts.update(p[:-len(SIDECAR)] for p in sidecars)
                    raise ValueError(f'destination collision: {target}')
                reserved[key] = item.record.id
                item.target = target
                if target != item.path:
                    proposal = {'record_id': item.record.id, 'from': item.path, 'to': target,
                                'sha256': item.record.sha, 'policy': 'uuid-date-v1'}
                    ctx.summary.proposals.append(proposal)
                    key = input_key(proposal)
                    if item.record.data['stages'].get('placement', {}).get('input_key') != key:
                        ctx.event(item.record, 'move_planned', **proposal)
                        ctx.complete(item.record, 'placement', key)
            except (ValueError, OSError) as error:
                ctx.fail(item, error)
        for item in batch:
            if item.path in conflicts and not item.blocked:
                ctx.fail(item, ValueError('file participates in a destination collision'))
        blocked_ids = {item.record.id for item in batch if item.blocked}
        ctx.summary.proposals[:] = [p for p in ctx.summary.proposals if p['record_id'] not in blocked_ids]


class ApplyMoves(ItemStage):
    def process(self, item, ctx):
        if not item.target or item.target == item.path or ctx.config.dry_run or not ctx.config.move_files:
            return
        stable(ctx.fs, item.path, item.observed)
        old = item.path
        intended = copy.deepcopy(item.record)
        intended.path = item.target
        ctx.event(intended, 'moved', **{'from': old, 'to': item.target, 'policy': 'uuid-date-v1'})
        item.record = ctx.moves.prepare(intended, old, item.target, item.sidecar_path)
        item.sidecar_path = item.target + SIDECAR
        item.saved = item.record.to_bytes()
        item.observed = ctx.fs.stat(item.path)
        ctx.summary.moved += 1


def default_stages():
    return (Observe(), Fingerprint(), ExtractMetadata(), ExactDuplicates(), PlanLocations(), ApplyMoves())
