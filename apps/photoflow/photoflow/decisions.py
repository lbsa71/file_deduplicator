"""Dated local choices keyed by exact media content, outside recoverable Trash."""

import json
import re
from datetime import datetime
from pathlib import PurePosixPath

from .content import fingerprint
from .model import Record, encoded

DECISIONS = '.photoflow/photo-decisions'
TRASH = '.photoflow/trash'


def decision_path(sha):
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise ValueError('photo decision requires a verified SHA-256')
    return f'{DECISIONS}/{sha}.json'


def read_decisions(fs, sha):
    path = decision_path(sha)
    if not fs.exists(path):
        return {}
    data = json.loads(fs.read_bytes(path))
    if not isinstance(data, dict) or set(data) - {'favorite', 'trashed'}:
        raise ValueError(f'invalid photo decisions: {path}')
    for field, decision in data.items():
        if (not isinstance(decision, dict) or 'value' not in decision
                or (type(decision['value']) is not bool
                    and not (field == 'favorite' and decision['value'] is None))
                or not isinstance(decision.get('at'), str)
                or datetime.fromisoformat(decision['at']).tzinfo is None):
            raise ValueError(f'invalid photo decision: {path}')
    return data


def trash_manifest(record):
    base = f'{TRASH}/{record.id}'
    return {'original_path': record.path, 'media': base + '/original' + PurePosixPath(record.path).suffix,
            'sidecar': base + '/record.json'}


def is_new_occurrence(record):
    return 'last_processed_at' not in record.data and record.data.get('lifecycle') != 'active'


def library_decisions(fs, library_id, batch, *, dry_run):
    current = {}
    for path in fs.list_files(DECISIONS):
        sha = PurePosixPath(path).stem
        if re.fullmatch(r'[0-9a-f]{64}', sha) and path == decision_path(sha):
            current[sha] = read_decisions(fs, sha)

    # Older sidecars already contain the dated actions. Use them when a
    # separate decision has not yet been written for that field and hash.
    historical = {}

    def add_history(record, sha):
        if not sha or not record.data['history']:
            return
        seen = set(current.get(sha, ()))
        for event in reversed(record.data['history']):
            kind, data = event['type'], event['data']
            if kind == 'content_changed':
                break
            if kind in ('trashed', 'restored'):
                field, value = 'trashed', kind == 'trashed'
            elif kind == 'metadata_edited' and type(data.get('set', {}).get('favorite')) is bool:
                field, value = 'favorite', data['set']['favorite']
            elif kind == 'metadata_edited' and 'favorite' in data.get('reset', ()):
                field, value = 'favorite', None
            else:
                continue
            if field in seen:
                continue
            seen.add(field)
            decisions = historical.setdefault(sha, {})
            previous = decisions.get(field)
            at = datetime.fromisoformat(event['at'])
            if previous is None or at > datetime.fromisoformat(previous['at']):
                decisions[field] = {'value': value, 'at': event['at'], 'record_id': record.id}

    for item in batch:
        if not item.blocked:
            add_history(item.record, item.record.sha)
    for path in fs.list_files(TRASH):
        if not path.endswith('/record.json'):
            continue
        record = Record.parse(fs.read_bytes(path), library_id)
        if record.data.get('lifecycle') == 'trashed':
            sha = record.sha or fingerprint(fs, trash_manifest(record)['media'])[0]
            add_history(record, sha)
    for sha, fields in historical.items():
        current.setdefault(sha, {}).update(fields)
        if not dry_run:
            fs.atomic_write(decision_path(sha), encoded(current[sha]))
    return current
