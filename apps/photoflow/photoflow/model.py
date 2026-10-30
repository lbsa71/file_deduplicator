"""Portable records and deterministic rules; no environmental access."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from uuid import UUID

SIDECAR = '.photo.json'
STATE = '.photoflow'
MARKER = STATE + '/library.json'
PENDING = STATE + '/pending'
APPLICATION_STATE = frozenset((STATE, '.takeout-extract'))


def auxiliary_name(name: str) -> bool:
    return name.startswith(('._', '.photoflow-tmp-')) or name in ('.DS_Store', '.AppleDouble', '__MACOSX')


def protected_directory(path: str) -> bool:
    return any(part in APPLICATION_STATE or auxiliary_name(part)
               for part in PurePosixPath(path).parts)


def relative_path(value: str, *, media: bool = False) -> str:
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('expected a nonempty POSIX relative path')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value or value == '.':
        raise ValueError(f'unsafe relative path: {value!r}')
    if media and (path.parts[0] == STATE or value.endswith(SIDECAR)):
        raise ValueError(f'not a media path: {value!r}')
    return value


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def input_key(value) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def timestamp(value: datetime) -> str:
    return value.isoformat().replace('+00:00', 'Z')


@dataclass(frozen=True)
class Signature:
    size: int
    mtime_ns: int
    ctime_ns: int
    device: int
    inode: int

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Inventory:
    files: tuple[str, ...]
    directories: tuple[str, ...]
    signatures: dict[str, Signature]


@dataclass
class Record:
    data: dict

    def to_bytes(self):
        # Keep the current snapshot easy to find without changing canonical
        # input-key encoding or retaining a second copy of aggregated metadata.
        first = ('schema_version', 'library_id', 'record_id', 'file', 'resolved',
                 'overrides', 'last_scanned_at', 'last_processed_at', 'duplicate_of',
                 'sources', 'stages')
        ordered = {key: self.data[key] for key in first if key in self.data}
        ordered.update((key, value) for key, value in self.data.items()
                       if key not in ordered and key != 'history')
        ordered['history'] = self.data['history']
        return (json.dumps(ordered, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')

    @property
    def id(self):
        return self.data['record_id']

    @property
    def file(self):
        return self.data['file']

    @property
    def path(self):
        return self.file['relative_path']

    @path.setter
    def path(self, value):
        self.file['relative_path'] = relative_path(value, media=True)

    @property
    def sha(self):
        return self.file.get('sha256')

    @classmethod
    def create(cls, record_id, library_id, path):
        name = PurePosixPath(path).name
        return cls({
            'schema_version': 1, 'library_id': library_id, 'record_id': record_id,
            'file': {'relative_path': path, 'sha256': None, 'fingerprint': None},
            'sources': [{'source_id': input_key([library_id, path]),
                         'original_filename': name, 'original_relative_path': path,
                         'documents': []}],
            'resolved': {}, 'overrides': {}, 'stages': {}, 'history': [],
        })

    @classmethod
    def parse(cls, raw: bytes, library_id: str):
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('schema_version') != 1:
            raise ValueError('unsupported or malformed record schema')
        if data.get('library_id') != library_id:
            raise ValueError('record belongs to another library')
        record_id = data.get('record_id')
        if not isinstance(record_id, str) or str(UUID(record_id)) != record_id:
            raise ValueError('record_id must be a canonical UUID')
        file = data.get('file')
        if not isinstance(file, dict):
            raise ValueError('missing file object')
        relative_path(file.get('relative_path'), media=True)
        for name in ('sha256', 'sample_sha256'):
            sha = file.get(name)
            if sha is not None and (not isinstance(sha, str) or len(sha) != 64
                                    or any(c not in '0123456789abcdef' for c in sha)):
                raise ValueError(f'invalid {name}')
        if 'size_bytes' in file and (type(file['size_bytes']) is not int or file['size_bytes'] < 0):
            raise ValueError('invalid size_bytes')
        signature = file.get('fingerprint')
        if signature is not None:
            if not isinstance(signature, dict) or set(signature) != set(Signature.__dataclass_fields__):
                raise ValueError('invalid fingerprint')
            if any(type(v) is not int or v < 0 for v in signature.values()):
                raise ValueError('invalid fingerprint values')
        for key in ('resolved', 'overrides', 'stages'):
            if not isinstance(data.get(key), dict):
                raise ValueError(f'missing {key} object')
        for section in ('resolved', 'overrides'):
            for key, value in data[section].items():
                if key in ('people', 'albums', 'place') and (not isinstance(value, list) or not all(isinstance(v, str) for v in value)):
                    raise ValueError(f'{section}.{key} must be a list of strings')
                if key in ('capture_time', 'description') and value is not None and not isinstance(value, str):
                    raise ValueError(f'{section}.{key} must be a string or null')
                if key == 'capture_time' and value is not None:
                    datetime.fromisoformat(value.replace('Z', '+00:00'))
        for name, checkpoint in data['stages'].items():
            if (not isinstance(checkpoint, dict) or not isinstance(checkpoint.get('input_key'), str)
                    or not isinstance(checkpoint.get('completed_at'), str)):
                raise ValueError(f'invalid stage checkpoint: {name}')
            if name == 'embedded_metadata' and not isinstance(checkpoint.get('result'), dict):
                raise ValueError('invalid embedded metadata result')
        if not isinstance(data.get('sources'), list) or not data['sources']:
            raise ValueError('missing source occurrences')
        for source in data['sources']:
            if not isinstance(source, dict) or not isinstance(source.get('source_id'), str):
                raise ValueError('invalid source occurrence')
            relative_path(source.get('original_relative_path'), media=True)
            if not isinstance(source.get('original_filename'), str) or not isinstance(source.get('documents'), list):
                raise ValueError('invalid source name or documents')
            for doc in source['documents']:
                if not isinstance(doc, dict) or not isinstance(doc.get('document'), dict):
                    raise ValueError('invalid imported document')
                relative_path(doc.get('relative_path'))
                if doc.get('kind') not in ('takeout', 'album') or not isinstance(doc.get('sha256'), str):
                    raise ValueError('invalid document provenance')
        history = data.get('history')
        if not isinstance(history, list) or any(
            not isinstance(e, dict) or e.get('seq') != i + 1
            or not all(isinstance(e.get(k), str) for k in ('event_id', 'run_id', 'at', 'type'))
            or not isinstance(e.get('data'), dict) for i, e in enumerate(history)
        ):
            raise ValueError('invalid event history')
        duplicate = data.get('duplicate_of')
        if duplicate is not None:
            if not isinstance(duplicate, dict) or not isinstance(duplicate.get('sha256'), str):
                raise ValueError('invalid duplicate relationship')
            duplicate_id = duplicate.get('record_id')
            if not isinstance(duplicate_id, str) or str(UUID(duplicate_id)) != duplicate_id:
                raise ValueError('invalid duplicate record UUID')
        return cls(data)


@dataclass
class WorkItem:
    record: Record
    observed: Signature
    sidecar_path: str
    saved: bytes | None = None
    blocked: bool = False
    target: str | None = None

    @property
    def path(self):
        return self.record.path


@dataclass
class Summary:
    run_id: str
    started_at: str | None = None
    completed_at: str | None = None
    discovered: int = 0
    processed: int = 0
    hashed: int = 0
    metadata_extracted: int = 0
    duplicates: int = 0
    moved: int = 0
    deferred: int = 0
    recovered: int = 0
    locked: bool = False
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    proposals: list = field(default_factory=list)
    removed_directories: list = field(default_factory=list)
    source_cache_hits: int = 0
    source_cache_misses: int = 0
    source_cache_writes: int = 0
    io: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def destination(record: Record, duplicate_policy: str = 'review') -> str:
    extension = PurePosixPath(record.path).suffix.lower()
    name = record.id + extension
    placement = record.data.get('placement', {})
    if placement.get('mode') == 'manual':
        folder = relative_path(placement['folder_path'])
        if not folder.startswith('folders/'):
            raise ValueError('manual placement requires a user folder')
        return f'{folder}/{name}'
    duplicate = record.data.get('duplicate_of')
    if duplicate and duplicate_policy == 'review':
        return f"review/duplicates/{duplicate['record_id']}/{name}"
    captured = record.data['resolved'].get('capture_time')
    if captured:
        date = datetime.fromisoformat(captured.replace('Z', '+00:00'))
        return f'photos/{date.year:04d}/{date.month:02d}/{name}'
    return f'undated/{name}'
