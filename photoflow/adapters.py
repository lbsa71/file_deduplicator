"""Local, POSIX filesystem and optional tool adapters."""

import ctypes
import errno
import fcntl
import json
import os
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from .model import APPLICATION_STATE, STATE, Signature, auxiliary_name, relative_path
from .ports import BusyError


@lru_cache(maxsize=1)
def _linux_renameat2():
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as error:
        raise OSError(errno.ENOSYS, 'libc renameat2 is required for no-overwrite moves') from error
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    return rename


def _rename_no_replace(source, target):
    if sys.platform == 'linux':
        # AT_FDCWD=-100, RENAME_NOREPLACE=1. One kernel operation rejects
        # occupied destinations, including on exFAT. Never fall back to an
        # exists()/rename() pair, which could overwrite a concurrent arrival.
        if _linux_renameat2()(-100, os.fsencode(source), -100, os.fsencode(target), 1):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), os.fspath(target))
    else:
        # Preserve the original POSIX adapter on platforms without renameat2.
        # Journal recovery also understands this legacy link/unlink sequence.
        os.link(source, target, follow_symlinks=False)
        os.unlink(source)


class LocalFileSystem:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('library root must be an existing directory')

    def native_path(self, path):
        relative_path(path)
        result = self.root / path
        for ancestor in (result, *result.parents):
            if ancestor == self.root:
                break
            if ancestor.is_symlink():
                raise ValueError(f'symlinks are not managed: {path}')
        return result

    def list_files(self, prefix=''):
        start = self.native_path(prefix) if prefix else self.root
        if not start.exists():
            return ()
        paths = []
        def fail(error):
            raise error
        for directory, dirs, files in os.walk(start, followlinks=False, onerror=fail):
            dirs[:] = sorted(d for d in dirs if not auxiliary_name(d)
                             and not (Path(directory) / d).is_symlink()
                             and not (not prefix and d in APPLICATION_STATE))
            for name in sorted(files):
                if auxiliary_name(name):
                    continue
                file = Path(directory) / name
                if file.is_symlink():
                    continue
                if stat.S_ISREG(file.stat(follow_symlinks=False).st_mode):
                    paths.append(file.relative_to(self.root).as_posix())
        return tuple(sorted(paths))

    def exists(self, path):
        return self.native_path(path).exists()

    def stat(self, path):
        value = self.native_path(path).stat(follow_symlinks=False)
        if not stat.S_ISREG(value.st_mode):
            raise ValueError(f'not a regular file: {path}')
        return Signature(value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_dev, value.st_ino)

    @contextmanager
    def open_binary(self, path):
        fd = os.open(self.native_path(path), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError(f'not a regular file: {path}')
            yield stream

    def read_bytes(self, path):
        with self.open_binary(path) as stream:
            # Managed/imported JSON is deliberately bounded; media uses streaming reads.
            value = stream.read(32 * 1024 * 1024 + 1)
        if len(value) > 32 * 1024 * 1024:
            raise ValueError(f'JSON exceeds the 32 MiB limit: {path}')
        return value

    @staticmethod
    def _sync_dir(directory):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _parents(self, target):
        missing = []
        parent = target.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            directory.mkdir(exist_ok=True)
            self._sync_dir(directory.parent)

    def atomic_write(self, path, data, *, replace=True):
        target = self.native_path(path)
        self._parents(target)
        fd, temporary = tempfile.mkstemp(prefix='.photoflow-tmp-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if replace:
                os.replace(temporary, target)
            else:
                _rename_no_replace(temporary, target)
            self._sync_dir(target.parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def move_no_replace(self, source, target):
        src, dst = self.native_path(source), self.native_path(target)
        self._parents(dst)
        with self.open_binary(source) as stream:
            os.fsync(stream.fileno())
        _rename_no_replace(src, dst)
        self._sync_dir(dst.parent)
        self._sync_dir(src.parent)

    def remove(self, path):
        target = self.native_path(path)
        target.unlink()
        self._sync_dir(target.parent)

    @contextmanager
    def lock(self):
        target = self.native_path(STATE + '/lock')
        fd = os.open(target, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise BusyError('another pass holds the library lock') from error
            yield
        finally:
            os.close(fd)


class SystemClock:
    def now(self):
        return datetime.now(timezone.utc)


class RandomIds:
    def new(self):
        return str(uuid4())


class NoEmbeddedMetadata:
    version = 'none-v1'

    def read(self, path):
        return {}


class ExifToolReader:
    def __init__(self, fs: LocalFileSystem, executable='exiftool'):
        self.fs = fs
        self.executable = executable
        result = subprocess.run([executable, '-ver'], check=True, capture_output=True, text=True, timeout=10)
        self.version = 'exiftool-v1:' + result.stdout.strip()

    def read(self, path):
        try:
            result = subprocess.run(
                [self.executable, '-json', '-G1', '-a', '-s', '-n', str(self.fs.native_path(path))],
                check=True, capture_output=True, text=True, timeout=60)
        except subprocess.SubprocessError as error:
            raise ValueError(f'ExifTool extraction failed for {path}: {error}') from error
        rows = json.loads(result.stdout)
        if len(rows) != 1 or not isinstance(rows[0], dict):
            raise ValueError('ExifTool must return exactly one metadata object')
        data = rows[0]
        data.pop('SourceFile', None)
        if 'ExifTool:Error' in data:
            raise ValueError(data['ExifTool:Error'])
        return data
