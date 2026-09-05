"""Exercise the real Tk UI when a graphical session is available."""

import os
import threading
import time
from pathlib import Path

import pytest

from carriola_downloader.engine import Cancelled
from carriola_downloader.ui import CarriolaApp

pytestmark = pytest.mark.skipif(
    os.name != "nt" and not os.environ.get("DISPLAY"), reason="A graphical session is required"
)


class UIEngine:
    ffmpeg = "ffmpeg"
    deno = None

    def __init__(self):
        self.release = threading.Event()
        self.started = threading.Event()

    def run(self, job, cancel, emit):
        self.started.set()
        emit(
            "progress",
            {
                "progress": 0.4,
                "title": "Vídeo de teste · ação 4K",
                "message": "Baixando arquivo de teste",
            },
        )
        while not self.release.wait(0.01):
            if cancel.is_set():
                raise Cancelled()
        if cancel.is_set():
            raise Cancelled()
        path = Path(job.destination) / "teste.mp4"
        path.write_bytes(b"fixture")
        emit("file", {"path": str(path), "title": "Vídeo de teste · ação 4K", "thumbnail": ""})
        return []


def pump(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.update()
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("UI did not reach the expected state")


@pytest.fixture
def app(tmp_path):
    engine = UIEngine()
    app = CarriolaApp(directory=tmp_path, engine=engine)
    app.store.set("notifications", False)
    app.destination.set(str(tmp_path))
    errors = []
    app.report_callback_exception = lambda *args: errors.append(args)
    yield app
    engine.release.set()
    app.on_close()
    pump(app, lambda: not app.downloads.is_alive())
    try:
        app.destroy()
    except Exception:
        pass
    assert errors == []


def test_queue_ui_completion_search_and_settings(app):
    app.url.set("https://youtu.be/test")
    app.add_download()
    pump(app, lambda: bool(app.cards))
    key = next(iter(app.cards))
    app.engine.release.set()
    pump(app, lambda: app.cards[key]["data"]["state"] == "completed")
    assert app.cards[key]["progress"].get() == 1
    app.search.insert(0, "not found")
    app.filter_cards()
    assert not app.cards[key]["frame"].winfo_manager()
    app.search.delete(0, "end")
    app.filter_cards()
    assert app.cards[key]["frame"].winfo_manager() == "pack"
    app.show_settings()
    app.update()
    assert app._settings.winfo_exists()
    app._settings.destroy()


def test_ui_cancels_individual_download_and_preserves_playlist_choice(app):
    app.url.set("https://youtube.com/playlist?list=123")
    assert app.playlist_value.get() is True
    app.url.set("https://youtu.be/test")
    assert app.playlist_value.get() is False
    app.add_download()
    pump(app, lambda: bool(app.cards) and app.engine.started.is_set())
    key = next(iter(app.cards))
    app.job_action(key)
    pump(app, lambda: app.cards[key]["data"]["state"] == "cancelled")
    assert app.cards[key]["primary"].cget("text") == "Tentar novamente"
    app.mode.set("Áudio")
    app.update_mode("Áudio")
    assert app.format.cget("values") == ["MP3", "WAV", "M4A"]
    assert app.quality.cget("state") == "disabled"
