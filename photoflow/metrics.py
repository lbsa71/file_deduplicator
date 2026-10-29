"""Optional counters at the filesystem port, rather than kernel/device counters."""

from collections import Counter, defaultdict
from contextlib import contextmanager

from .model import SIDECAR, STATE


class _Reader:
    def __init__(self, stream, counters):
        self.stream, self.counters = stream, counters

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def read(self, size=-1):
        data = self.stream.read(size)
        self.counters['read_calls'] += 1
        self.counters['read_bytes'] += len(data)
        return data

    def readinto(self, buffer):
        count = self.stream.readinto(buffer)
        self.counters['read_calls'] += 1
        self.counters['read_bytes'] += count or 0
        return count


class MeteredFileSystem:
    def __init__(self, fs):
        self.fs = fs
        self.operations = Counter()
        self.files = defaultdict(Counter)

    def __getattr__(self, name):
        return getattr(self.fs, name)

    def _file(self, path):
        role = ('state' if path.startswith(STATE + '/') else
                'sidecar' if path.endswith(SIDECAR) else
                'source_json' if path.endswith('.json') else 'media')
        return self.files[role]

    def inventory(self, prefix=''):
        self.operations['inventory'] += 1
        result = self.fs.inventory(prefix)
        self.operations['enumerated_files'] += len(result.files)
        self.operations['enumerated_directories'] += len(result.directories)
        return result

    def list_files(self, prefix=''):
        self.operations['list_files'] += 1
        return self.fs.list_files(prefix)

    def list_directories(self):
        self.operations['list_directories'] += 1
        return self.fs.list_directories()

    def stat(self, path):
        self.operations['stat'] += 1
        self._file(path)['stat_calls'] += 1
        return self.fs.stat(path)

    def exists(self, path):
        self.operations['exists'] += 1
        self._file(path)['exists_calls'] += 1
        return self.fs.exists(path)

    def read_bytes(self, path):
        self.operations['read_bytes'] += 1
        data = self.fs.read_bytes(path)
        counters = self._file(path)
        counters['read_opens'] += 1
        counters['read_calls'] += 1
        counters['read_bytes'] += len(data)
        return data

    @contextmanager
    def open_binary(self, path):
        self.operations['open_binary'] += 1
        with self.fs.open_binary(path) as stream:
            counters = self._file(path)
            counters['read_opens'] += 1
            yield _Reader(stream, counters)

    def atomic_write(self, path, data, *, replace=True):
        self.operations['atomic_write'] += 1
        self.fs.atomic_write(path, data, replace=replace)
        self._file(path)['atomic_writes'] += 1
        self._file(path)['written_bytes'] += len(data)

    def move_no_replace(self, source, target):
        self.operations['move_no_replace'] += 1
        return self.fs.move_no_replace(source, target)

    def remove(self, path):
        self.operations['remove'] += 1
        return self.fs.remove(path)

    def remove_empty_directory(self, path):
        self.operations['remove_empty_directory'] += 1
        removed = self.fs.remove_empty_directory(path)
        self.operations['directories_removed'] += bool(removed)
        return removed

    @contextmanager
    def lock(self):
        self.operations['lock'] += 1
        with self.fs.lock():
            yield

    def stats(self):
        return {'scope': 'filesystem port calls and payload bytes; excludes internal path checks, '
                         'ExifTool reads, kernel syscalls, and physical device I/O',
                'operations': dict(self.operations),
                'files': {role: dict(counts) for role, counts in self.files.items()}}
