"""Replay web mutation intents under the common library lock."""

import json
import hashlib
from pathlib import Path
from .adapters import _rename_no_replace
from .model import encoded


def recover(fs):
    for manifest in fs.list_files(".photoflow/web-operations"):
        if not manifest.endswith(".json"):
            continue
        op = json.loads(fs.read_bytes(manifest))
        for move in op.get("moves", []):
            src, dst = fs.native_path(move["from"]), fs.native_path(move["to"])
            expected = move.get("sha256")
            existing = src if src.exists() else dst
            if expected:
                before = existing.stat()
                with existing.open("rb") as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != expected or any(
                    getattr(before, key) != getattr(existing.stat(), key)
                    for key in (
                        "st_size",
                        "st_mtime_ns",
                        "st_ctime_ns",
                        "st_ino",
                        "st_dev",
                    )
                ):
                    raise ValueError("Recovery content conflict")
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    raise ValueError("Recovery destination occupied")
                _rename_no_replace(src, dst)
                fs._sync_dir(src.parent)
                fs._sync_dir(dst.parent)
            elif not dst.exists():
                raise ValueError("Recovery source missing")
        for path, data in op.get("writes", {}).items():
            desired = encoded(data)
            if "expected_writes" in op and fs.exists(path):
                actual = hashlib.sha256(fs.read_bytes(path)).hexdigest()
                if actual not in (
                    op["expected_writes"].get(path),
                    hashlib.sha256(desired).hexdigest(),
                ):
                    raise ValueError("Recovery metadata conflict; preserving operation")
            fs.atomic_write(path, desired)
        for path in op.get("remove", []):
            if fs.exists(path):
                fs.remove(path)
        fs.remove(manifest)
