"""Lossless Takeout import and small, deterministic resolution rules."""

import copy
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import PurePosixPath

from .model import input_key
from .content import stable
from .ports import ChangedError
from .source_cache import SourceCache

RESOLVER_VERSION = 'takeout-and-exif-v1'


def read_document(fs, path, kind):
    before = fs.stat(path)
    raw = fs.read_bytes(path)
    stable(fs, path, before)
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError(f'expected a JSON object: {path}')
    return {'kind': kind, 'relative_path': path,
            'sha256': hashlib.sha256(raw).hexdigest(), 'document': document}


class SourceCatalog:
    """Per-pass association index backed by disposable source-document caches."""

    def __init__(self, fs, inventory, library_id, *, verify, summary):
        self.fs, self.inventory = fs, inventory
        self.verify, self.summary = verify, summary
        self.cache = SourceCache(fs, library_id, summary)
        self.documents, self.titles = {}, {}
        self.by_parent = defaultdict(list)
        for path in sorted(inventory):
            if path.endswith('.supplemental-metadata.json'):
                self.by_parent[PurePosixPath(path).parent].append(path)

    def read(self, path, kind):
        key = (path, kind)
        if key not in self.documents:
            before = self.fs.stat(path)
            cached = None if self.verify else self.cache.get(path, before)
            if cached is not None:
                stable(self.fs, path, before)
                self.summary.source_cache_hits += 1
                self.documents[key] = {'kind': kind, 'relative_path': path, **cached}
            else:
                self.summary.source_cache_misses += 1
                document = read_document(self.fs, path, kind)
                if self.fs.stat(path) != before:
                    raise ChangedError(f'source JSON changed during processing: {path}')
                self.cache.put(path, before, document)
                self.documents[key] = document
        return self.documents[key]

    def save(self):
        self.cache.save()

    def matching_titles(self, parent, title):
        if parent not in self.titles:
            index = defaultdict(list)
            for path in self.by_parent[parent]:
                try:
                    name = self.read(path, 'takeout')['document'].get('title')
                    if isinstance(name, str):
                        index[name].append(path)
                except (ValueError, OSError):
                    # A malformed unrelated document stays unmatched; exact
                    # associations still raise an error when that file is read.
                    continue
            self.titles[parent] = index
        return self.titles[parent].get(title, [])


def import_sources(record, catalog):
    """Revisit preserved source paths, even after the media has been moved."""
    changed = False
    used = set()
    inventory = catalog.inventory
    for source in record.data['sources']:
        original = source['original_relative_path']
        paths = [original]
        if record.path != original:
            paths.append(record.path)
        found = []
        for media_path in paths:
            parent = PurePosixPath(media_path).parent
            exact = [media_path + '.supplemental-metadata.json', media_path + '.json']
            for candidate in exact:
                if candidate in inventory:
                    found.append((candidate, 'takeout'))
            # Truncated Takeout names can be matched by title only when unique
            # within this immediate directory. No recursive/fuzzy guessing.
            if not any(candidate in inventory for candidate in exact):
                candidates = catalog.matching_titles(parent, source['original_filename'])
                if len(candidates) > 1:
                    raise ValueError(f'ambiguous Takeout title association for {original}')
                if candidates:
                    found.append((candidates[0], 'takeout'))
            album_path = (parent / 'metadata.json').as_posix()
            if album_path in inventory and media_path == original:
                found.append((album_path, 'album'))
        for path, kind in dict.fromkeys(found):
            doc = catalog.read(path, kind)
            used.add(path)
            if not any((d['relative_path'], d['sha256'], d['kind']) == (path, doc['sha256'], kind)
                       for d in source['documents']):
                source['documents'].append(copy.deepcopy(doc))
                changed = True
    return changed, used


def valid_date(value):
    if not isinstance(value, str) or not value:
        return None
    # ExifTool often emits YYYY:MM:DD HH:MM:SS, with optional timezone.
    if len(value) >= 19 and value[4] == ':' and value[7] == ':':
        value = value[:10].replace(':', '-') + 'T' + value[11:]
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return value


def resolve(record):
    provenance = {k: [] for k in ('capture_time', 'people', 'albums', 'description')}

    def add(field, value, source, detail):
        if value is not None and value != '':
            assertion = {'value': value, 'source': source, 'field': detail}
            if assertion not in provenance[field]:
                provenance[field].append(assertion)

    embedded = record.data['stages'].get('embedded_metadata', {}).get('result', {})
    # Prefer the actual capture field; filesystem/upload timestamps are not capture dates.
    for key in ('Composite:SubSecDateTimeOriginal', 'ExifIFD:DateTimeOriginal', 'EXIF:DateTimeOriginal', 'DateTimeOriginal',
                'QuickTime:CreateDate'):
        if date := valid_date(embedded.get(key)):
            if 'DateTimeOriginal' in key and datetime.fromisoformat(date.replace('Z', '+00:00')).tzinfo is None:
                for offset_key in ('ExifIFD:OffsetTimeOriginal', 'EXIF:OffsetTimeOriginal', 'OffsetTimeOriginal'):
                    offset = embedded.get(offset_key)
                    if isinstance(offset, str) and valid_date(date + offset):
                        date += offset
                        key += ' + ' + offset_key
                        break
            add('capture_time', date, 'embedded', key)
            break
    for source in record.data['sources']:
        # Retain every revision, but resolve using the latest document per path/kind.
        latest = {}
        for doc in source['documents']:
            latest[(doc['relative_path'], doc['kind'])] = doc
        for doc in latest.values():
            raw = doc['document']
            origin = {'source_id': source['source_id'], 'path': doc['relative_path'],
                      'sha256': doc['sha256']}
            if doc['kind'] == 'album':
                title = raw.get('title')
                if isinstance(title, str):
                    add('albums', title, origin, 'title')
                continue
            taken = raw.get('photoTakenTime')
            if isinstance(taken, dict) and 'timestamp' in taken:
                try:
                    date = datetime.fromtimestamp(int(taken['timestamp']), timezone.utc)
                    add('capture_time', date.isoformat().replace('+00:00', 'Z'), origin, 'photoTakenTime.timestamp')
                except (ValueError, TypeError, OverflowError, OSError):
                    pass
            people = raw.get('people', [])
            if isinstance(people, list):
                for person in people:
                    if isinstance(person, dict) and isinstance(person.get('name'), str):
                        add('people', person['name'], origin, 'people.name')
            if isinstance(raw.get('description'), str):
                add('description', raw['description'], origin, 'description')
    resolved = {'capture_time': None, 'people': [], 'albums': [], 'description': ''}
    for field, assertions in provenance.items():
        if field in ('people', 'albums'):
            resolved[field] = sorted({a['value'] for a in assertions})
        elif assertions:
            resolved[field] = assertions[0]['value']
    for field, value in record.data['overrides'].items():
        if field not in resolved:
            continue
        if field == 'capture_time' and value is not None and valid_date(value) is None:
            raise ValueError('capture_time override must be an ISO date/time or null')
        resolved[field] = copy.deepcopy(value)
        provenance[field].append({'value': copy.deepcopy(value), 'source': 'human', 'field': field})
    resolved['provenance'] = provenance
    return resolved


def resolution_key(record):
    return input_key([RESOLVER_VERSION, record.data['sources'], record.data['overrides'],
                      record.data['stages'].get('embedded_metadata')])


def merge_sources(target, incoming):
    changed = False
    by_id = {s['source_id']: s for s in target.data['sources']}
    for source in incoming.data['sources']:
        if source['source_id'] not in by_id:
            copied = copy.deepcopy(source)
            target.data['sources'].append(copied)
            by_id[source['source_id']] = copied
            changed = True
        else:
            documents = by_id[source['source_id']]['documents']
            for doc in source['documents']:
                if doc not in documents:
                    documents.append(copy.deepcopy(doc))
                    changed = True
    return changed
