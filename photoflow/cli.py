"""Configuration, dependency wiring, and structured terminal output."""

import argparse
import json
import subprocess
import sys
import time

from . import __version__
from .adapters import ExifToolReader, LocalFileSystem, NoEmbeddedMetadata, RandomIds, SystemClock
from .model import MARKER, SIDECAR, Record, encoded
from .metrics import MeteredFileSystem
from .runner import Config, MEDIA_EXTENSIONS, Runner


def parser():
    root = argparse.ArgumentParser(prog='photoflow', description='Incrementally refine a filesystem photo library.')
    root.add_argument('--version', action='version', version=__version__)
    commands = root.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='mark an existing directory as a library')
    init.add_argument('root')
    init.add_argument('--library-id', help='persistent identity (default: a random UUID)')
    run = commands.add_parser('run', help='perform one finite, locked pass')
    run.add_argument('root')
    run.add_argument('--dry-run', action='store_true', help='preview without writing any files')
    run.add_argument('--no-move', action='store_true', help='save metadata and proposals without relocating media')
    run.add_argument('--verify', action='store_true', help='recompute full hashes regardless of stat caches')
    run.add_argument('--settle-seconds', type=float, default=30, help='minimum quiet period (default: 30)')
    run.add_argument('--audit-every-scan', action='store_true')
    run.add_argument('--duplicates', choices=('review', 'keep'), default='review')
    run.add_argument('--expect-library-id', help='refuse to run against another library')
    run.add_argument('--extensions', help='comma-separated suffixes, overriding the default media list')
    run.add_argument('--exiftool', action='store_true', help='extract embedded metadata using installed ExifTool')
    run.add_argument('--stats', action='store_true', help='include filesystem access counters and elapsed time')
    search = commands.add_parser('search', help='search original names and resolved metadata without writing')
    search.add_argument('root')
    search.add_argument('query')
    return root


def initialize(fs, library_id):
    if fs.exists(MARKER):
        marker = json.loads(fs.read_bytes(MARKER))
        if library_id and marker.get('library_id') != library_id:
            raise ValueError('library is already initialized with a different identity')
        return marker
    marker = {'schema_version': 1, 'library_id': library_id or RandomIds().new()}
    if not marker['library_id'].strip():
        raise ValueError('library identity cannot be blank')
    fs.atomic_write(MARKER, encoded(marker), replace=False)
    return marker


def search_records(fs, query):
    marker = json.loads(fs.read_bytes(MARKER))
    matches, errors = [], []
    needle = query.casefold()
    for path in fs.list_files():
        if not path.endswith(SIDECAR):
            continue
        try:
            record = Record.parse(fs.read_bytes(path), marker['library_id'])
            resolved = record.data['resolved']
            row = {'record_id': record.id, 'relative_path': record.path,
                   'original_filenames': sorted({s['original_filename'] for s in record.data['sources']}),
                   'people': resolved.get('people', []), 'albums': resolved.get('albums', []),
                   'description': resolved.get('description', ''),
                   'capture_time': resolved.get('capture_time')}
            if needle in json.dumps(row, ensure_ascii=False).casefold():
                matches.append(row)
        except (ValueError, OSError, TypeError) as error:
            errors.append(f'{path}: {error}')
    return matches, errors


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        fs = LocalFileSystem(args.root)
        if args.command == 'init':
            print(encoded(initialize(fs, args.library_id)).decode(), end='')
            return 0
        if args.command == 'search':
            matches, errors = search_records(fs, args.query)
            print(encoded(matches).decode(), end='')
            if errors:
                print(encoded({'errors': errors}).decode(), file=sys.stderr, end='')
            return 1 if errors else 0
        extensions = MEDIA_EXTENSIONS
        if args.extensions:
            extensions = frozenset('.' + value.strip().lower().lstrip('.')
                                   for value in args.extensions.split(',') if value.strip())
            if not extensions or any('/' in suffix or '\\' in suffix for suffix in extensions):
                raise ValueError('extensions must be comma-separated filename suffixes')
        config = Config(dry_run=args.dry_run, move_files=not args.no_move,
                        verify=args.verify, settle_seconds=args.settle_seconds,
                        audit_every_scan=args.audit_every_scan, duplicates=args.duplicates,
                        expected_library_id=args.expect_library_id, extensions=extensions)
        started = time.perf_counter()
        if args.stats:
            fs = MeteredFileSystem(fs)
        reader = ExifToolReader(fs) if args.exiftool else NoEmbeddedMetadata()
        result = Runner(fs, SystemClock(), RandomIds(), reader, config).run()
        if args.stats:
            result.io = fs.stats()
            result.io['elapsed_seconds'] = round(time.perf_counter() - started, 6)
        print(encoded(result.to_dict()).decode(), end='')
        return 1 if result.errors else 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(encoded({'error': str(error)}).decode(), file=sys.stderr, end='')
        return 2
