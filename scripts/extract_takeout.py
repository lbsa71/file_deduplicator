"""Verified, restartable extraction of finalized Takeout ZIPs into one shared root.

Run from the checkout: python3 -m scripts.extract_takeout ROOT ARCHIVE --delete
"""

import argparse
import fcntl
import hashlib
import json
import ntpath
import os
import re
import stat
import sys
import tempfile
import unicodedata
import uuid
import zipfile
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photoflow.adapters import LocalFileSystem, _rename_no_replace
from photoflow.model import relative_path

STATE = '.takeout-extract'
ARCHIVE = re.compile(r'takeout-20261028T123735Z-1-(\d{3})\.zip')
BLOCK = 1024 * 1024


class ExtractionError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _key(path):
    # Uppercase also joins exFAT aliases such as dotless i and ASCII i.
    return unicodedata.normalize('NFC', path).upper().casefold()


def _signature(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


@contextmanager
def _open_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ExtractionError(f'not a regular file: {path}')
        yield stream


def _digest(stream):
    digest, crc, size = hashlib.sha256(), 0, 0
    while block := stream.read(BLOCK):
        digest.update(block)
        crc = zlib.crc32(block, crc)
        size += len(block)
    return {'size': size, 'crc32': crc, 'sha256': digest.hexdigest()}


def _file_info(path):
    with _open_regular(path) as stream:
        before = _signature(os.fstat(stream.fileno()))
        result = _digest(stream)
        if _signature(os.fstat(stream.fileno())) != before:
            raise ExtractionError(f'file changed during verification: {path}')
        if _signature(path.stat(follow_symlinks=False)) != before:
            raise ExtractionError(f'file was replaced during verification: {path}')
        return result


def _save(fs, path, value):
    fs.atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


@contextmanager
def _lock(fs, name):
    target = fs.native_path(f'{STATE}/locks/{name}.lock')
    fs._parents(target)
    fd = os.open(target, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _path_lock(fs, path):
    return _lock(fs, 'path-' + hashlib.sha256(_key(path).encode()).hexdigest())


def _member_path(name):
    if not isinstance(name, str) or not name or '\x00' in name or '\\' in name:
        raise ExtractionError(f'unsafe archive member: {name!r}')
    value = name[:-1] if name.endswith('/') else name
    path = PurePosixPath(value)
    if (not value or value == '.' or not path.parts or path.is_absolute() or ntpath.splitdrive(value)[0]
            or path.as_posix() != value or any(part in ('.', '..') for part in path.parts)
            or any(part.endswith(('.', ' ')) for part in path.parts)):
        raise ExtractionError(f'unsafe archive member: {name!r}')
    if _key(path.parts[0]) == _key(STATE) or path.parts[0].lower().startswith('takeout-20261028t123735z-1-'):
        raise ExtractionError(f'archive member overlaps extraction state or ZIP inputs: {name!r}')
    return path.as_posix()


def _preflight(archive, root, *, check_space=True, output_prefix='', archive_relative_path=None):
    entries, kinds = [], {}
    for info in archive.infolist():
        member = _member_path(info.orig_filename)
        path = _member_path(f'{output_prefix}/{member}') if output_prefix else member
        if archive_relative_path and _key(path) == _key(archive_relative_path):
            raise ExtractionError(f'extracted output aliases its input archive: {path}')
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
            raise ExtractionError(f'unsupported special/encrypted entry: {info.filename!r}')
        directory = info.is_dir()
        if kind == stat.S_IFDIR and not directory:
            raise ExtractionError(f'inconsistent directory entry: {info.filename!r}')
        if directory and (info.file_size != 0 or info.CRC != 0):
            raise ExtractionError(f'directory entry contains an unchecked payload: {info.filename!r}')
        key = _key(path)
        if key in kinds and kinds[key] != directory:
            raise ExtractionError(f'file/directory collision: {path}')
        kinds[key] = directory
        entries.append((info, path, directory))
    for _, path, directory in entries:
        for parent in PurePosixPath(path).parents:
            if parent.as_posix() != '.' and kinds.get(_key(parent.as_posix())) is False:
                raise ExtractionError(f'file used as parent directory: {path}')
    # Output plus one member's temporary verification copy needs bounded headroom.
    needed = sum(info.file_size for info, _, directory in entries if not directory)
    largest = max((info.file_size for info, _, directory in entries if not directory), default=0)
    import shutil
    if check_space and needed + largest > shutil.disk_usage(root).free:
        raise ExtractionError('insufficient free space for declared archive contents')
    return entries


def _verify_membership(saved, members):
    expected = {path: (info.file_size, info.CRC) for info, path, directory in members if not directory}
    entries = saved['entries']
    actual = {_member_path(entry['path']): (entry['size'], entry['crc32']) for entry in entries}
    expected_dirs = {path for _, path, directory in members if directory}
    actual_dirs = {_member_path(path) for path in saved.get('directories', [])}
    if actual != expected or len(entries) != len(expected) or actual_dirs != expected_dirs:
        raise ExtractionError('completion record does not cover current archive membership/size/CRC')


def _extract_file(fs, archive, info, path):
    with _path_lock(fs, path):
        target = fs.native_path(path)
        fs._parents(target)
        fd, temporary = tempfile.mkstemp(prefix='.tx-', dir=target.parent)
        try:
            digest, crc, size = hashlib.sha256(), 0, 0
            with os.fdopen(fd, 'wb') as output, archive.open(info) as source:
                while block := source.read(BLOCK):
                    size += len(block)
                    if size > info.file_size:
                        raise ExtractionError(f'entry exceeds declared size: {path}')
                    output.write(block)
                    digest.update(block)
                    crc = zlib.crc32(block, crc)
                output.flush()
                os.fsync(output.fileno())
            expected = {'size': size, 'crc32': crc, 'sha256': digest.hexdigest()}
            if size != info.file_size or crc != info.CRC:
                raise ExtractionError(f'archive entry failed size/CRC verification: {path}')
            existing = target.exists()
            if not existing:
                try:
                    _rename_no_replace(temporary, target)
                    fs._sync_dir(target.parent)
                except FileExistsError:
                    # A filesystem alias or a noncooperating creator may race
                    # our path lock. Inspect it; never replace it.
                    existing = True
            if existing and _file_info(target) != expected:
                raise ExtractionError(f'existing output differs; preserved output and archive: {path}')
            return {'path': path, **expected}, existing
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _verify_outputs(fs, entries, directories):
    for directory in directories:
        path = fs.native_path(_member_path(directory))
        if not path.is_dir():
            raise ExtractionError(f'missing extracted directory: {directory}')
    for entry in entries:
        path = _member_path(entry['path'])
        with _path_lock(fs, path):
            if _file_info(fs.native_path(path)) != {key: entry[key] for key in ('size', 'crc32', 'sha256')}:
                raise ExtractionError(f'extracted output failed verification: {path}')


def _assert_archive_name(path, source):
    if _signature(path.stat(follow_symlinks=False)) != _signature(os.fstat(source.fileno())):
        raise ExtractionError('archive pathname changed while processing; archive retained')


def _remove_archive(fs, path, source, report, completion_path):
    # Quarantine the name before unlinking: even a raced replacement is never
    # deleted unless the moved inode is the held, verified input descriptor.
    staged = f'{STATE}/deleting/{report["archive_number"]:03d}-{uuid.uuid4().hex}.zip'
    destination = fs.native_path(staged)
    fs._parents(destination)
    report['archive_deleted'] = False
    report['staged_archive'] = staged
    _save(fs, completion_path, report)
    _assert_archive_name(path, source)
    _rename_no_replace(path, destination)
    fs._sync_dir(path.parent)
    fs._sync_dir(destination.parent)
    try:
        _assert_archive_name(destination, source)
        if _file_info(destination)['sha256'] != report['archive_sha256']:
            raise ExtractionError('archive changed before deletion; archive retained')
    except Exception:
        try:
            _rename_no_replace(destination, path)
            fs._sync_dir(path.parent)
            fs._sync_dir(destination.parent)
        except OSError:
            pass  # Preserve the staged file if another archive now owns the name.
        raise
    destination.unlink()
    fs._sync_dir(destination.parent)
    report['archive_deleted'] = True
    report['staged_archive'] = None
    _save(fs, completion_path, report)


def _finish_staged(fs, saved, completion_path, delete):
    staged = saved.get('staged_archive')
    if staged:
        if not staged.startswith(STATE + '/deleting/') or '..' in PurePosixPath(staged).parts:
            raise ExtractionError('invalid staged archive path in completion record')
        path = fs.native_path(staged)
        if path.exists():
            if _file_info(path)['sha256'] != saved['archive_sha256']:
                raise ExtractionError('staged archive conflicts with completion record')
            with zipfile.ZipFile(path) as archive:
                _verify_membership(saved, _preflight(archive, fs.root, check_space=False,
                    output_prefix=saved.get('output_prefix', ''),
                    archive_relative_path=saved.get('archive_relative_path', saved['archive_name'])))
            _verify_outputs(fs, saved['entries'], saved.get('directories', []))
            if delete:
                path.unlink()
                fs._sync_dir(path.parent)
            else:
                return False
        saved['staged_archive'] = None
        _save(fs, completion_path, saved)
    return True


def _resume_without_input(fs, saved, completion_path, delete):
    _verify_outputs(fs, saved['entries'], saved.get('directories', []))
    if _finish_staged(fs, saved, completion_path, delete):
        saved['archive_deleted'] = True
        _save(fs, completion_path, saved)
    return saved


def extract_archive(root, archive_name, *, delete=False):
    match = ARCHIVE.fullmatch(archive_name) if isinstance(archive_name, str) else None
    if not match or not 1 <= int(match[1]) <= 25:
        raise ExtractionError('expected a finalized Takeout ZIP numbered 001 through 025')
    return _extract_job(root, archive_name, int(match[1]), '', delete)


def extract_legacy_archive(root, archive_relative_path, *, archive_number, output_prefix, delete=False):
    """Expand a working-copy ZIP beneath a stable, explicitly chosen group."""
    try:
        relative_path(archive_relative_path)
        if (ntpath.splitdrive(archive_relative_path)[0]
                or PurePosixPath(archive_relative_path).suffix.lower() != '.zip'
                or _key(PurePosixPath(archive_relative_path).parts[0]) == _key(STATE)):
            raise ValueError('expected a regular ZIP input outside extraction state')
        prefix = _member_path(output_prefix)
        if type(archive_number) is not int or not 1 <= archive_number <= 999:
            raise ValueError('archive_number must be a stable integer from 1 through 999')
    except (TypeError, ValueError) as error:
        raise ExtractionError(str(error)) from error
    return _extract_job(root, archive_relative_path, archive_number, prefix, delete)


def _extract_job(root, archive_name, number, output_prefix, delete):
    try:
        fs = LocalFileSystem(root)
        archive_path = fs.native_path(archive_name)
    except (OSError, ValueError) as error:
        raise ExtractionError(str(error)) from error
    completion = f'{STATE}/completed/{number:03d}.json'
    with _lock(fs, f'archive-{number:03d}'):
        try:
            saved = json.loads(fs.read_bytes(completion)) if fs.exists(completion) else None
            if saved and (saved.get('archive_name') != archive_name or saved.get('schema_version') != 1
                    or saved.get('archive_relative_path', saved.get('archive_name')) != archive_name
                    or saved.get('archive_number') != number
                    or saved.get('output_prefix', '') != output_prefix):
                raise ExtractionError('completion record belongs to another archive or output prefix')
            if not archive_path.exists():
                if saved:
                    return _resume_without_input(fs, saved, completion, delete)
                raise ExtractionError('finalized ZIP not found')
            with _open_regular(archive_path) as source:
                before = _signature(os.fstat(source.fileno()))
                archive_hash = _digest(source)['sha256']
                if _signature(os.fstat(source.fileno())) != before:
                    raise ExtractionError('archive changed while hashing')
                if saved:
                    if saved['archive_sha256'] != archive_hash:
                        raise ExtractionError('same-named ZIP differs from completed archive; retained')
                    source.seek(0)
                    with zipfile.ZipFile(source) as archive:
                        _verify_membership(saved, _preflight(archive, fs.root, check_space=False,
                            output_prefix=output_prefix, archive_relative_path=archive_name))
                    _verify_outputs(fs, saved['entries'], saved.get('directories', []))
                    _assert_archive_name(archive_path, source)
                    if delete:
                        _finish_staged(fs, saved, completion, delete=True)
                        _remove_archive(fs, archive_path, source, saved, completion)
                    return saved
                source.seek(0)
                entries, directories, existing = {}, [], 0
                with zipfile.ZipFile(source) as archive:
                    members = _preflight(archive, fs.root, output_prefix=output_prefix,
                        archive_relative_path=archive_name)
                    for index, (info, path, directory) in enumerate(members):
                        if directory:
                            target = fs.native_path(path)
                            fs._parents(target / '.entry')
                            directories.append(path)
                        else:
                            entry, already_exists = _extract_file(fs, archive, info, path)
                            entries[path] = entry
                            existing += already_exists
                        if index % 100 == 0 or index + 1 == len(members):
                            _save(fs, f'{STATE}/running/{number:03d}.json', {
                                'archive_name': archive_name, 'entries_done': index + 1,
                                'entries_total': len(members), 'at': _now()})
                if _signature(os.fstat(source.fileno())) != before:
                    raise ExtractionError('archive changed during extraction; retained')
                _assert_archive_name(archive_path, source)
                _verify_outputs(fs, list(entries.values()), directories)
                report = {'schema_version': 1, 'status': 'completed', 'archive_name': archive_name,
                    'archive_relative_path': archive_name, 'output_prefix': output_prefix,
                    'archive_number': number, 'archive_sha256': archive_hash,
                    'archive_size': before[2], 'entries': list(entries.values()),
                    'directories': sorted(set(directories)), 'existing_files': existing,
                    'completed_at': _now(), 'archive_deleted': False, 'staged_archive': None}
                _save(fs, completion, report)
                if delete:
                    _remove_archive(fs, archive_path, source, report, completion)
                return report
        except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile, ExtractionError) as error:
            try:
                _save(fs, f'{STATE}/failed/{number:03d}.json', {
                    'archive_name': archive_name, 'status': 'failed', 'error': str(error), 'at': _now()})
            except OSError:
                pass
            if isinstance(error, ExtractionError):
                raise
            raise ExtractionError(str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('archive')
    parser.add_argument('--delete', action='store_true', help='remove ZIP only after verified extraction')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(extract_archive(args.root, args.archive, delete=args.delete), ensure_ascii=False))
        return 0
    except ExtractionError as error:
        print(json.dumps({'status': 'failed', 'archive_name': args.archive, 'error': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
