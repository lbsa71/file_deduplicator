"""Bounded, deduplicated thumbnail jobs outside HTTP handlers."""

import concurrent.futures, hashlib, os, subprocess, threading
from pathlib import Path
import shutil
import time


class Media:
    levels = (64, 256, 512, 1024, 2048)

    def __init__(self, library, cache):
        self.library = library
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.pool = concurrent.futures.ThreadPoolExecutor(2)
        self.pending = {}
        self.failed = {}
        self.lock = threading.Lock()
        self.last_gc = 0
        self.gc_lock = threading.Lock()

    def variant(self, record, level):
        if level not in self.levels:
            raise ValueError("Invalid level")
        if self.library.fs.stat(record["file"]["relative_path"]).to_dict() != record[
            "file"
        ].get("fingerprint"):
            raise ValueError("Source changed; reconcile the library before rendering")
        key = hashlib.sha256(
            f"{record['file']['sha256']}:v1:{record['resolved'].get('display_rotation',0)}:{level}".encode()
        ).hexdigest()
        p = self.cache / key[:2] / (key + ".webp")
        if p.exists():
            return p, "ready"
        with self.lock:
            if key in self.failed:
                return None, "failed"
            if key not in self.pending:
                self.pending[key] = self.pool.submit(self.render, record, level, p, key)
        return None, "pending"

    def render(self, record, level, target, key):
        temp = None
        try:
            if shutil.disk_usage(self.cache).free < 2 * 1024**3:
                raise OSError("Thumbnail disk is low on space")
            self.collect_cache()
            source = self.library.path(record["file"]["relative_path"])
            before = source.stat()
            target.parent.mkdir(exist_ok=True)
            temp = target.with_name(target.stem + ".tmp.webp")
            video = source.suffix.lower() in (
                ".mov",
                ".mp4",
                ".m4v",
                ".avi",
                ".mkv",
                ".mts",
                ".3gp",
            )
            if video:
                command = [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-threads",
                    "1",
                    "-filter_threads",
                    "1",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={level}:{level}:force_original_aspect_ratio=decrease",
                    "-c:v",
                    "libwebp",
                    "-threads",
                    "1",
                    "-y",
                    str(temp),
                ]
            else:
                command = [
                    "vipsthumbnail",
                    str(source),
                    "--size",
                    str(level) + "x" + str(level) + ">",
                    "-o",
                    str(temp) + "[Q=80,strip]",
                ]
            import sys

            subprocess.run(
                [sys.executable, "-m", "photoflow_web.decoder", *command],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
            rotation = record["resolved"].get("display_rotation", 0)
            if rotation:
                from PIL import Image

                with Image.open(temp) as image:
                    image.rotate(-rotation, expand=True).save(temp, "WEBP", quality=80)
            if source.stat() != before:
                raise ValueError("Source changed")
            os.replace(temp, target)
        except Exception as error:
            self.failed[key] = type(error).__name__
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
            with self.lock:
                self.pending.pop(key, None)

    def collect_cache(self):
        if time.monotonic() - self.last_gc < 60 or not self.gc_lock.acquire(
            blocking=False
        ):
            return
        try:
            self.last_gc = time.monotonic()
            entries = []
            for path in self.cache.glob("*/*.webp"):
                if ".tmp." not in path.name:
                    stat = path.stat()
                    entries.append((stat.st_mtime, stat.st_size, path))
            total = sum(e[1] for e in entries)
            if total > 20 * 1024**3:
                for _, size, path in sorted(entries):
                    if path.stem in self.pending:
                        continue
                    path.unlink(missing_ok=True)
                    total -= size
                    if total <= 16 * 1024**3:
                        break
        finally:
            self.gc_lock.release()
