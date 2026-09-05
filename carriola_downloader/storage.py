"""SQLite history; user data never belongs beside an installed executable."""

import configparser
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

from .models import ACTIVE, Job


def data_directory() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "CarriolaDownloaderDev"


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "history.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, job: Job):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO jobs VALUES (?, ?)",
                (job.id, json.dumps(job.snapshot(), ensure_ascii=False)),
            )

    def jobs(self) -> list[Job]:
        with self.connect() as db:
            rows = db.execute("SELECT data FROM jobs").fetchall()
        return sorted((Job(**json.loads(row[0])) for row in rows), key=lambda job: job.created)

    def recover(self) -> list[Job]:
        jobs = self.jobs()
        for job in jobs:
            if job.state in ACTIVE:
                job.state = "interrupted"
                job.message = "Interrompido ao fechar. Use Tentar novamente para continuar."
                self.save(job)
        return jobs

    def remove(self, ids: list[str]):
        with self.connect() as db:
            db.executemany("DELETE FROM jobs WHERE id = ?", ((item,) for item in ids))

    def get(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))

    def import_legacy_config(self, path: Path):
        if self.get("legacy_config_checked", False):
            return
        config = configparser.ConfigParser()
        try:
            config.read(path, encoding="utf-8-sig")
            destination = config.get("DEFAULT", "download_path", fallback="")
            if destination and self.get("download_path") is None:
                self.set("download_path", destination)
        except (configparser.Error, UnicodeError, OSError):
            pass
        self.set("legacy_config_checked", True)
