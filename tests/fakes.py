import io
from contextlib import contextmanager
from dataclasses import replace
from uuid import UUID
from pathlib import PurePosixPath

from photoflow.model import APPLICATION_STATE, Inventory, Signature, auxiliary_name, protected_directory, relative_path
from photoflow.ports import BusyError


class FakeClock:
    def __init__(self, now):
        self.value = now

    def now(self):
        return self.value


class FakeIds:
    def __init__(self):
        self.counter = 0

    def new(self):
        self.counter += 1
        return str(UUID(int=self.counter))


class MetadataReader:
    version = 'fixture-v1'

    def __init__(self):
        self.calls = []
        self.on_read = None
        self.result = {}

    def read(self, path):
        self.calls.append(path)
        if self.on_read:
            callback, self.on_read = self.on_read, None
            callback()
        return self.result.copy()


class MemoryFS:
    def __init__(self):
        self.data = {}
        self.directories = set()
        self.signatures = {}
        self.tick = 0
        self.on_read = None
        self.fail_on = None
        self.busy = False

    def _fault(self, operation, path):
        if self.fail_on:
            self.fail_on(operation, path)

    def put(self, path, data):
        if path in self.directories:
            raise IsADirectoryError(path)
        parent = PurePosixPath(path).parent.as_posix()
        if parent != '.':
            self.mkdir(parent)
        self.tick += 1
        self.data[path] = data
        self.signatures[path] = Signature(len(data), self.tick, self.tick, 1, self.tick)

    def inventory(self, prefix=''):
        files = [path for path in self.data if not any(auxiliary_name(part) for part in PurePosixPath(path).parts)]
        directories = [path for path in self.directories if not any(auxiliary_name(part) for part in PurePosixPath(path).parts)]
        if prefix:
            files = [p for p in files if p.startswith(prefix + '/')]
            directories = [p for p in directories if p.startswith(prefix + '/')]
        else:
            files = [p for p in files if not protected_directory(p)]
            directories = [p for p in directories if not protected_directory(p)]
        return Inventory(tuple(sorted(files)), tuple(sorted(directories)),
                         {p: self.signatures[p] for p in files})

    def list_files(self, prefix=''):
        return self.inventory(prefix).files

    def exists(self, path):
        return path in self.data or path in self.directories

    def mkdir(self, path):
        relative_path(path)
        for candidate in (PurePosixPath(path), *PurePosixPath(path).parents):
            name = candidate.as_posix()
            if name == '.':
                continue
            if name in self.data:
                raise FileExistsError(name)
            self.directories.add(name)

    def list_directories(self):
        return self.inventory().directories

    def remove_empty_directory(self, path):
        relative_path(path)
        if protected_directory(path):
            raise ValueError(f'protected directory: {path}')
        self._fault('rmdir', path)
        if path not in self.directories:
            return False
        if any(p.startswith(path + '/') for p in self.data.keys() | self.directories):
            return False
        self.directories.remove(path)
        return True

    def stat(self, path):
        return self.signatures[path]

    def read_bytes(self, path):
        return self.data[path]

    @contextmanager
    def open_binary(self, path):
        value = self.data[path]
        if self.on_read:
            callback, self.on_read = self.on_read, None
            callback(path)
        yield io.BytesIO(value)

    def atomic_write(self, path, data, *, replace=True):
        self._fault('write', path)
        if not replace and path in self.data:
            raise FileExistsError(path)
        self.put(path, data)

    def link(self, source, target):
        if target in self.data:
            raise FileExistsError(target)
        parent = PurePosixPath(target).parent.as_posix()
        if parent != '.':
            self.mkdir(parent)
        self.data[target] = self.data[source]
        self.tick += 1
        signature = replace(self.signatures[source], ctime_ns=self.tick)
        self.signatures[target] = signature
        self.signatures[source] = signature

    def move_no_replace(self, source, target):
        self._fault('move', target)
        self.link(source, target)
        self._fault('linked', target)
        self.remove(source)
        self._fault('moved', target)

    def remove(self, path):
        self._fault('remove', path)
        del self.data[path]
        del self.signatures[path]

    @contextmanager
    def lock(self):
        if self.busy:
            raise BusyError('locked')
        self.busy = True
        try:
            yield
        finally:
            self.busy = False
