"""Real yt-dlp + FFmpeg round trips against a local HTTP media server."""

import functools
import json
import shutil
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yt_dlp
from PIL import Image
from yt_dlp.extractor.common import InfoExtractor

from carriola_downloader.engine import DownloadEngine
from carriola_downloader.models import Job

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg and FFprobe required"
)


@pytest.fixture(scope="module")
def media_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("media")
    Image.new("RGB", (320, 180), "red").save(root / "cover.png")

    def generate(*args):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, timeout=30
        )

    generate(
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=3840x2160:r=2",
        "-t",
        "1",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(root / "video.mp4"),
    )
    generate(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=44100",
        "-t",
        "1",
        "-c:a",
        "aac",
        "-vn",
        str(root / "audio.m4a"),
    )

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(3)


@pytest.fixture
def fixture_extractor(media_server, monkeypatch):
    class FixtureIE(InfoExtractor):
        _VALID_URL = r"fixture:(?P<id>[a-z0-9]+)"

        def _real_extract(self, url):
            return {
                "id": self._match_id(url),
                "title": 'Ação: "Carriola"? / 4K 💿',
                "thumbnail": media_server + "/cover.png",
                "formats": [
                    {
                        "format_id": "audio",
                        "url": media_server + "/audio.m4a",
                        "ext": "m4a",
                        "acodec": "aac",
                        "vcodec": "none",
                    },
                    {
                        "format_id": "4k",
                        "url": media_server + "/video.mp4",
                        "ext": "mp4",
                        "width": 3840,
                        "height": 2160,
                        "vcodec": "h264",
                        "acodec": "none",
                    },
                ],
            }

    original = yt_dlp.YoutubeDL

    def factory(opts):
        instance = original(opts, auto_init=False)
        instance.add_info_extractor(FixtureIE())
        return instance

    monkeypatch.setattr(yt_dlp, "YoutubeDL", factory)


@pytest.mark.parametrize(
    "mode,codec,container",
    [
        ("video", "mp3", "mp4"),
        ("video", "mp3", "mkv"),
        ("audio", "wav", "mp4"),
        ("audio", "mp3", "mp4"),
        ("audio", "m4a", "mp4"),
    ],
)
def test_real_media_output(mode, codec, container, fixture_extractor, tmp_path):
    engine = DownloadEngine(shutil.which("ffmpeg"))
    job = Job(
        "fixture:source", str(tmp_path / "100% edição"), mode=mode, codec=codec, container=container
    )
    events = []
    errors = engine.run(job, threading.Event(), lambda kind, data: events.append((kind, data)))
    assert errors == []
    files = [data for kind, data in events if kind == "file"]
    assert len(files) == 1
    output = Path(files[0]["path"])
    assert output.is_file()
    assert output.suffix == "." + (container if mode == "video" else codec)
    assert "Ação" in output.name
    assert "/" not in output.name and "?" not in output.name and ":" not in output.name
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    streams = json.loads(result.stdout)["streams"]
    assert any(stream["codec_type"] == "audio" for stream in streams)
    if mode == "video":
        video = next(stream for stream in streams if stream["codec_type"] == "video")
        assert video["width"] == 3840 and video["height"] == 2160
    else:
        assert all(
            stream["codec_type"] == "audio" or stream.get("disposition", {}).get("attached_pic")
            for stream in streams
        )
        if codec in {"mp3", "m4a"}:
            assert any(stream.get("disposition", {}).get("attached_pic") for stream in streams)
        else:
            assert all(stream["codec_type"] == "audio" for stream in streams)
    # Repeating a completed download must keep the same final file and report it.
    original_mtime = output.stat().st_mtime_ns
    again = []
    engine.run(job, threading.Event(), lambda kind, data: again.append((kind, data)))
    assert [data["path"] for kind, data in again if kind == "file"] == [str(output)]
    assert output.stat().st_mtime_ns == original_mtime
