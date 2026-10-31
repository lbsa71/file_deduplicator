"""Bounded original imports. Signed URLs are used transiently, never journaled."""

import hashlib, io, os, time, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from PIL import Image
from photoflow.model import Record, SIDECAR
from photoflow.runner import MEDIA_EXTENSIONS
from .core import atomic, load

MAX_ORIGINAL = 16 * 1024**2
FORMATS = {"PNG": ("image/png", {".png"}), "JPEG": ("image/jpeg", {".jpg", ".jpeg"}),
           "WEBP": ("image/webp", {".webp"})}


def approved_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("Invalid original URL")
    u = urlsplit(value)
    if (u.scheme != "https" or u.username or u.password or u.port not in (None, 443)
        or u.fragment or not (u.hostname == "photos.google.com" or
                              u.hostname == "googleusercontent.com" or
                              (u.hostname or "").endswith(".googleusercontent.com"))):
        raise ValueError("Unapproved original host")
    return value


def download_original(url, transport=None):
    # No Google cookies, authorization headers, redirects, environment proxies or retries.
    approved_url(url)
    deadline = time.monotonic() + 90
    with httpx.Client(timeout=httpx.Timeout(30, read=60), follow_redirects=False, trust_env=False, transport=transport) as client:
        with client.stream("GET", url) as response:
            if response.status_code != 200:
                if response.status_code in (401, 403):
                    raise ValueError("GOOGLE_AUTH_REQUIRED")
                if 300 <= response.status_code < 400:
                    raise ValueError("GOOGLE_REDIRECT")
                raise ValueError("GOOGLE_HTTP")
            declared = response.headers.get("content-length")
            if declared is not None and (not declared.isdecimal() or not 0 < int(declared) <= MAX_ORIGINAL):
                raise ValueError("Invalid original size")
            raw = bytearray()
            for part in response.iter_bytes(chunk_size=64 * 1024):
                if time.monotonic() > deadline:
                    raise ValueError("Original transport failed")
                raw.extend(part)
                if len(raw) > MAX_ORIGINAL:
                    raise ValueError("Original exceeds single-image limit")
            if declared is not None and len(raw) != int(declared):
                raise ValueError("Incomplete original")
            return bytes(raw), response.headers.get("content-type", "").split(";")[0].strip().lower()


def file_sha(path):
    before = path.stat()
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if any(getattr(before, key) != getattr(after, key) for key in
           ("st_size", "st_mtime_ns", "st_ctime_ns", "st_ino", "st_dev")):
        raise ValueError("Local original changed during duplicate verification")
    return sha


class OriginalImporter:
    def __init__(self, library, fetch=download_original):
        self.library, self.fetch = library, fetch

    def receipt_path(self, job):
        if not isinstance(job, str) or not job or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in job):
            raise ValueError("Invalid download job")
        return self.library.root / ".photoflow/google-downloads" / (job + ".json")

    def import_one(self, owner, account, job, photo, url, active=lambda: None):
        if photo.get("companion") is True:
            raise ValueError("Motion-photo companions require a paired import")
        name, size = photo["filename"], photo["size"]
        suffix = Path(name).suffix.lower()
        if (Path(name).name != name or "\\" in name or suffix not in {".jpg", ".jpeg", ".png", ".webp"}
            or type(size) is not int or not 0 < size <= MAX_ORIGINAL):
            raise ValueError("Single-image import requires a supported original under 16 MiB")
        receipt_path = self.receipt_path(job)
        with self.library.mutex:
            active()
            # Replay an acknowledged local transfer only for the exact same job.
            # Across jobs, Google IDs alone are not content equality: fetch and hash.
            with self.library.writer():
                previous = load(receipt_path)
                if previous:
                    for relative in self.library.fs.list_files():
                        if relative.endswith(SIDECAR):
                            record = load(self.library.path(relative))
                            if record["record_id"] == previous["recordId"] and previous["mediaKey"] == photo["mediaKey"] and previous["bytes"] == size:
                                if file_sha(self.library.path(record["file"]["relative_path"])) != previous["sha256"]:
                                    raise ValueError("Imported original changed")
                                self.finalize(record, record["file"]["relative_path"], receipt_path, previous)
                                return previous
                    raise ValueError("Import receipt has no matching local original")
            approved_url(url)
            try:
                raw, mime = self.fetch(url)
            except httpx.HTTPError:
                raise ValueError("Original transport failed") from None
            zipped = isinstance(raw, bytes) and raw.startswith(b"PK\x03\x04")
            if zipped:
                if mime not in {"application/zip", "application/octet-stream"} or len(raw) > MAX_ORIGINAL:
                    raise ValueError("Invalid original archive")
                try:
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        members = archive.infolist()
                        if len(members) != 1:
                            raise ValueError("Expected exactly one original in archive")
                        member = members[0]
                        if (member.filename != name or member.is_dir() or member.file_size != size
                            or member.flag_bits & 1 or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                            raise ValueError("Original archive target or size disagrees with Google details")
                        with archive.open(member) as stream:
                            raw = stream.read(size + 1)
                except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
                    raise ValueError("Invalid original archive") from None
            if not isinstance(raw, bytes) or len(raw) != size or len(raw) > MAX_ORIGINAL:
                raise ValueError("Original byte size disagrees with Google details")
            with Image.open(io.BytesIO(raw)) as image:
                expected = FORMATS.get(image.format)
                if not expected or (not zipped and mime != expected[0]) or suffix not in expected[1] or image.width * image.height > 100_000_000:
                    raise ValueError("Original image format disagrees with metadata")
                image.verify()
            sha = hashlib.sha256(raw).hexdigest()
            with self.library.writer():
                active()
                record, target, moves = None, None, []
                # Recheck filesystem authority after the network read, including uncatalogued media.
                for relative in self.library.fs.list_files():
                    path = self.library.path(relative)
                    if Path(relative).suffix.lower() in MEDIA_EXTENSIONS and path.stat().st_size == size and file_sha(path) == sha:
                        sidecar = self.library.path(relative + SIDECAR)
                        if not sidecar.exists():
                            raise ValueError("Matching original lacks a record; reconcile the library first")
                        record, target = load(sidecar), relative
                        break
                outcome = "already-present" if record else "imported"
                if record is None:
                    ident = str(uuid.uuid4())
                    target = f"inbox/google/{ident}{suffix}"
                    stage = f".photoflow/google-downloads/{job}.partial"
                    path = self.library.path(stage)
                    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                        output.write(raw); output.flush(); os.fsync(output.fileno())
                    record = Record.create(ident, self.library.id, target).data
                    record["file"].update(sha256=sha, size_bytes=size)
                    record["sources"][0]["original_filename"] = name
                    stamp = photo.get("timestampMs")
                    if type(stamp) is int:
                        record["resolved"]["capture_time"] = datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
                    moves = [{"from": stage, "to": target}]
                sources = record.setdefault("google_originals", [])
                if not any(s.get("account") == account and s.get("mediaKey") == photo["mediaKey"] for s in sources):
                    sources.append({"account": account, "mediaKey": photo["mediaKey"], "dedupKey": photo["dedupKey"], "sha256": sha, "observation": photo})
                self.library.event(record, owner, "google-original-imported" if outcome == "imported" else "google-original-reused", job=job)
                result = self.result(photo, record["record_id"], sha, size, outcome)
                self.library.transaction(moves, {target + SIDECAR: record,
                    str(receipt_path.relative_to(self.library.root)): result})
                self.finalize(record, target, receipt_path, result)
                return result

    def finalize(self, record, target, receipt_path, result):
        # Rename can change ctime. Publish the verified final signature only after
        # the recoverable move, so media can render immediately without a scan.
        before = self.library.fs.stat(target)
        if file_sha(self.library.path(target)) != result["sha256"] or self.library.fs.stat(target) != before:
            raise ValueError("Imported original changed before catalog publication")
        record["file"].update(sha256=result["sha256"], size_bytes=result["bytes"], fingerprint=before.to_dict())
        self.library.transaction([], {target + SIDECAR: record,
            str(receipt_path.relative_to(self.library.root)): result})
        self.library.put_index(record, self.library.path(target + SIDECAR))

    @staticmethod
    def result(photo, record, sha, size, outcome):
        return {"mediaKey": photo["mediaKey"], "recordId": record, "sha256": sha,
                "bytes": size, "outcome": outcome, "retentionReady": False}
