"""One journal per move/relink; replay finishes the same intended record."""

import copy
import json

from .content import fingerprint
from .model import PENDING, SIDECAR, Record, encoded, relative_path


class MoveJournal:
    def __init__(self, fs, ids, library_id):
        self.fs, self.ids, self.library_id = fs, ids, library_id

    def _check_sidecar(self, path, record_id):
        if self.fs.exists(path):
            record = Record.parse(self.fs.read_bytes(path), self.library_id)
            if record.id != record_id:
                raise ValueError(f'sidecar collision at {path}')

    def _verify(self, path, expected_sha):
        if fingerprint(self.fs, path)[0] != expected_sha:
            raise ValueError(f'content conflict at {path}; pending operation retained')

    def prepare(self, record, source, target, old_sidecar):
        relative_path(source, media=True)
        relative_path(target, media=True)
        if source != target and self.fs.exists(target):
            raise FileExistsError(f'destination already exists: {target}')
        self._check_sidecar(target + SIDECAR, record.id)
        self._check_sidecar(old_sidecar, record.id)
        journal_path = PENDING + '/' + self.ids.new() + '.json'
        intent = {'schema_version': 1, 'library_id': self.library_id,
                  'source': source, 'target': target, 'old_sidecar': old_sidecar,
                  'sha256': record.sha, 'record': copy.deepcopy(record.data)}
        self.fs.atomic_write(journal_path, encoded(intent), replace=False)
        return self.finish(journal_path, intent)

    def finish(self, journal_path, intent):
        if intent.get('schema_version') != 1 or intent.get('library_id') != self.library_id:
            raise ValueError(f'invalid journal: {journal_path}')
        record = Record.parse(encoded(intent['record']), self.library_id)
        source = relative_path(intent['source'], media=True)
        target = relative_path(intent['target'], media=True)
        old_sidecar = relative_path(intent['old_sidecar'])
        if not old_sidecar.endswith(SIDECAR) or intent['sha256'] != record.sha or record.path != target or not record.sha:
            raise ValueError(f'inconsistent journal: {journal_path}')
        new_sidecar = target + SIDECAR
        self._check_sidecar(old_sidecar, record.id)
        self._check_sidecar(new_sidecar, record.id)
        if self.fs.exists(target):
            self._verify(target, record.sha)
            if source != target and self.fs.exists(source):
                self._verify(source, record.sha)
                a, b = self.fs.stat(source), self.fs.stat(target)
                if (a.device, a.inode) != (b.device, b.inode):
                    raise ValueError(f'ambiguous destination collision at {target}')
                # Interrupted link/unlink: both paths name the very same inode.
                self.fs.remove(source)
        else:
            if not self.fs.exists(source):
                raise ValueError(f'both media paths missing for {journal_path}')
            self._verify(source, record.sha)
            self.fs.move_no_replace(source, target)
            self._verify(target, record.sha)
        record.file['fingerprint'] = self.fs.stat(target).to_dict()
        self.fs.atomic_write(new_sidecar, record.to_bytes(), replace=self.fs.exists(new_sidecar))
        if old_sidecar != new_sidecar and self.fs.exists(old_sidecar):
            self.fs.remove(old_sidecar)
        self.fs.remove(journal_path)
        return record

    def recover(self):
        recovered = 0
        for path in self.fs.list_files(PENDING):
            if path.endswith('.json'):
                self.finish(path, json.loads(self.fs.read_bytes(path)))
                recovered += 1
        return recovered
