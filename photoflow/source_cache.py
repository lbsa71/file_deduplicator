"""Disposable, bounded source-JSON cache shards; originals remain authoritative."""

import hashlib
import json

from .model import encoded, input_key


class SourceCache:
    def __init__(self, fs, library_id, summary):
        self.fs, self.library_id, self.summary = fs, library_id, summary
        self.buckets, self.dirty = {}, set()

    def _bucket(self, path):
        name = hashlib.sha256(path.encode()).hexdigest()[:2]
        if name not in self.buckets:
            entries = {}
            cache_path = f'.photoflow/source-cache/{name}.json'
            try:
                if self.fs.exists(cache_path):
                    value = json.loads(self.fs.read_bytes(cache_path))
                    if (not isinstance(value, dict) or value.get('schema_version') != 1
                            or value.get('library_id') != self.library_id
                            or not isinstance(value.get('entries'), dict)):
                        raise ValueError('invalid cache schema or library identity')
                    entries = value['entries']
            except (OSError, ValueError) as error:
                self.summary.warnings.append(f'source_cache_ignored: {cache_path}: {error}')
            self.buckets[name] = entries
        return name, self.buckets[name]

    def get(self, path, signature):
        _, entries = self._bucket(path)
        value = entries.get(path)
        if not isinstance(value, dict) or value.get('signature') != signature.to_dict():
            return None
        document, sha = value.get('document'), value.get('sha256')
        try:
            valid = (isinstance(document, dict) and isinstance(sha, str) and len(sha) == 64
                     and all(c in '0123456789abcdef' for c in sha)
                     and value.get('key') == input_key([sha, document]))
        except (TypeError, ValueError):
            valid = False
        if not valid:
            self.summary.warnings.append(f'source_cache_ignored: invalid entry for {path}')
            return None
        return {'sha256': sha, 'document': document}

    def put(self, path, signature, document):
        name, entries = self._bucket(path)
        sha, raw = document['sha256'], document['document']
        value = {'signature': signature.to_dict(), 'sha256': sha, 'document': raw,
                 'key': input_key([sha, raw])}
        if entries.get(path) != value:
            entries[path] = value
            self.dirty.add(name)

    def save(self):
        for name in sorted(self.dirty):
            path = f'.photoflow/source-cache/{name}.json'
            try:
                self.fs.atomic_write(path, encoded({'schema_version': 1,
                    'library_id': self.library_id, 'entries': self.buckets[name]}))
                self.summary.source_cache_writes += 1
            except (OSError, ValueError) as error:
                self.summary.warnings.append(f'source_cache_write_failed: {path}: {error}')
