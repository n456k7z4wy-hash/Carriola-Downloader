import threading
from pathlib import Path

import pytest
import yt_dlp

from carriola_downloader.engine import (
    Cancelled,
    DownloadEngine,
    format_bytes,
    format_time,
    video_selector,
)
from carriola_downloader.models import Job, playlist_kind, validate_url
from carriola_downloader.queue_manager import DownloadQueue
from carriola_downloader.storage import Store


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=abc",
        "https://youtu.be/abc",
        "https://m.youtube.com/shorts/abc",
        "https://www.instagram.com/reel/abc/",
        "https://x.com/user/status/123",
    ],
)
def test_supported_urls(url):
    assert validate_url("  " + url + "  ") == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://youtube.com.evil.example/watch?v=1",
        "javascript:alert(1)",
        "https://evil.example/youtube.com",
        "https://user:secret@youtube.com/watch?v=1",
        "https://youtube.com:99999/watch?v=1",
        "https://youtube.com/watch?v=1\nhttps://x.com/a",
        "https://youtube.com",
        "not a URL",
        "https://youtube.com:9000/watch?v=1",
    ],
)
def test_reject_invalid_or_spoofed_urls(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_playlist_detection():
    assert playlist_kind("https://[") is None
    assert playlist_kind("https://youtube.com/playlist?list=PL123") == "playlist"
    assert playlist_kind("https://youtube.com/watch?list=PL123&v=abc") == "video"
    assert playlist_kind("https://youtu.be/abc?list=PL123") == "video"
    assert playlist_kind("https://x.com/playlist/status/1") is None


def video(identifier, width, height, *, audio=False, ext="mp4"):
    return {
        "format_id": identifier,
        "width": width,
        "height": height,
        "vcodec": "av01",
        "acodec": "aac" if audio else "none",
        "ext": ext,
        "protocol": "https",
    }


AUDIO = {"format_id": "audio", "vcodec": "none", "acodec": "aac", "ext": "m4a", "protocol": "https"}


@pytest.mark.parametrize(
    "dimensions", [(3840, 2160), (2160, 3840), (3840, 1600), (2160, 2160), (4096, 2160)]
)
def test_4k_selection_preserves_both_streams(dimensions):
    formats = [AUDIO, video("360", 640, 360, audio=True), video("4k", *dimensions)]
    selected = list(video_selector(2160, "mp4")({"formats": formats}))[0]
    assert selected["format_id"] == "4k+audio"
    assert len(selected["requested_formats"]) == 2


def test_quality_limit_does_not_select_4k():
    formats = [AUDIO, video("1080", 1920, 1080), video("4k", 3840, 2160)]
    assert list(video_selector(1080, "mp4")({"formats": formats}))[0]["format_id"] == "1080+audio"


def test_missing_audio_does_not_silently_download_silent_video_or_360p():
    formats = [video("360", 640, 360, audio=True), video("4k", 3840, 2160)]
    with pytest.raises(yt_dlp.utils.DownloadError, match="áudio"):
        list(video_selector(2160, "mp4")({"formats": formats}))


def test_progressive_source_with_sound_is_supported():
    fmt = video("direct", 1920, 1080, audio=True)
    assert list(video_selector(0, "mp4")({"formats": [fmt]})) == [fmt]


def test_wav_does_not_request_unsupported_thumbnail_embedding(tmp_path):
    engine = DownloadEngine("ffmpeg")
    job = Job("https://youtu.be/abc", str(tmp_path / "100% música"), mode="audio", codec="wav")
    job.validate()
    options = engine.options(job, lambda _: None, lambda _: None, None)
    assert "EmbedThumbnail" not in [item["key"] for item in options["postprocessors"]]
    assert not options.get("writethumbnail", False)
    assert "100%% música" in options["outtmpl"]
    assert options["continuedl"] is True
    assert options["overwrites"] is False


def test_output_paths_distinguish_quality_and_media_id(tmp_path):
    engine = DownloadEngine("ffmpeg")
    one = engine.options(Job("https://youtu.be/a", str(tmp_path), quality=1080), None, None, None)
    two = engine.options(Job("https://youtu.be/a", str(tmp_path), quality=2160), None, None, None)
    assert one["outtmpl"] != two["outtmpl"]
    assert "%(id)s" in one["outtmpl"]


def test_progress_helpers_handle_zero_unknown_and_non_numeric_values():
    assert format_time(0) == "00:00"
    assert format_time(None) == "--:--"
    assert format_time(3600) == "01:00:00"
    assert format_bytes(1024) == "1.0 KiB"
    assert format_bytes(float("nan")) == "0.0 B"
    assert format_bytes("\x1b[0m25%") == "0.0 B"


def test_history_recovery_preserves_completed_files_and_unicode(tmp_path):
    store = Store(tmp_path)
    pending = Job("https://youtu.be/a", str(tmp_path), state="running", title="Ação 💿")
    completed = Job(
        "https://youtu.be/b",
        str(tmp_path),
        state="completed",
        files=[{"path": "C:/Áudio/ação.mp3"}],
    )
    store.save(pending)
    store.save(completed)
    restored = {job.id: job for job in Store(tmp_path).recover()}
    assert restored[pending.id].state == "interrupted"
    assert restored[pending.id].title == "Ação 💿"
    assert restored[completed.id].files == completed.files
    assert restored[completed.id].state == "completed"


def test_legacy_destination_import_is_non_destructive(tmp_path):
    legacy = tmp_path / "carriola_config.ini"
    original = "[DEFAULT]\ndownload_path = C:/Vídeos\n"
    legacy.write_text(original, encoding="utf-8")
    store = Store(tmp_path / "data")
    store.import_legacy_config(legacy)
    assert store.get("download_path") == "C:/Vídeos"
    store.set("download_path", "D:/New")
    store.import_legacy_config(legacy)
    assert store.get("download_path") == "D:/New"
    assert legacy.read_text(encoding="utf-8") == original


class ControlledEngine:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def run(self, job, cancel, emit):
        self.calls.append(job.id)
        self.started.set()
        if len(self.calls) == 1:
            while not self.release.wait(0.01):
                if cancel.is_set():
                    raise Cancelled()
        if cancel.is_set():
            raise Cancelled()
        path = Path(job.destination) / f"{job.id}.mp4"
        path.write_bytes(b"test fixture")
        emit("file", {"path": str(path), "title": "Concluído", "thumbnail": ""})
        return []


@pytest.fixture
def queue(tmp_path):
    engine = ControlledEngine()
    result = DownloadQueue(Store(tmp_path), engine)
    yield result, engine
    engine.release.set()
    result.close()
    result._thread.join(5)
    assert not result.is_alive()


def test_cancel_active_item_does_not_cancel_next_download(queue, tmp_path):
    downloads, engine = queue
    first = downloads.submit(Job("https://youtu.be/a", str(tmp_path)))
    assert engine.started.wait(3)
    second = downloads.submit(Job("https://youtu.be/b", str(tmp_path)))
    downloads.cancel(first)
    downloads._pending.join()
    states = {job["id"]: job["state"] for job in downloads.snapshots()}
    assert states == {first: "cancelled", second: "completed"}


def test_pending_cancellation_and_retry_runs_once(queue, tmp_path):
    downloads, engine = queue
    first = downloads.submit(Job("https://youtu.be/a", str(tmp_path)))
    assert engine.started.wait(3)
    second = downloads.submit(Job("https://youtu.be/b", str(tmp_path)))
    downloads.cancel(second)
    downloads.retry(second)
    engine.release.set()
    downloads._pending.join()
    assert engine.calls == [first, second]
    assert downloads.jobs[second].state == "completed"


def test_duplicate_active_job_rejected(queue, tmp_path):
    downloads, engine = queue
    downloads.submit(Job("https://youtu.be/a", str(tmp_path)))
    assert engine.started.wait(3)
    with pytest.raises(ValueError, match="já está na fila"):
        downloads.submit(Job("https://youtu.be/a", str(tmp_path)))


def test_clearing_history_keeps_actual_files(queue, tmp_path):
    downloads, engine = queue
    key = downloads.submit(Job("https://youtu.be/a", str(tmp_path)))
    engine.release.set()
    downloads._pending.join()
    actual = Path(downloads.jobs[key].files[0]["path"])
    downloads.clear_finished()
    assert actual.is_file()
    assert downloads.store.jobs() == []


def test_partial_playlist_keeps_successful_files(tmp_path):
    class PartialEngine:
        def run(self, job, cancel, emit):
            emit("file", {"path": "downloaded.mp4", "title": "Video 1", "thumbnail": ""})
            return ["Video 2 is private"]

    queue = DownloadQueue(Store(tmp_path), PartialEngine())
    try:
        key = queue.submit(
            Job("https://youtube.com/playlist?list=123", str(tmp_path), playlist=True)
        )
        queue._pending.join()
        assert queue.jobs[key].state == "partial"
        assert len(queue.jobs[key].files) == 1
        assert "private" in queue.jobs[key].error
    finally:
        queue.close()
        queue._thread.join(3)


def test_closed_queue_rejects_new_work(queue, tmp_path):
    downloads, _ = queue
    downloads.close()
    with pytest.raises(ValueError, match="encerrando"):
        downloads.submit(Job("https://youtu.be/a", str(tmp_path)))
