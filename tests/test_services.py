import json
from io import BytesIO
from queue import Queue

import pytest
from PIL import Image

from carriola_downloader import REPO_URL, services


def test_release_lookup_only_returns_trusted_release_link(monkeypatch):
    data = {"tag_name": "v15.2", "html_url": REPO_URL + "/releases/tag/v15.2"}
    monkeypatch.setattr(services, "fetch_bytes", lambda *args: json.dumps(data).encode())
    assert services.published_release() == {"tag": "v15.2", "url": data["html_url"]}
    data["html_url"] = "https://example.com/installer.exe"
    with pytest.raises(ValueError, match="inesperado"):
        services.published_release()


def test_thumbnail_cache_does_not_collide_on_same_url_suffix(tmp_path, monkeypatch):
    def image_bytes(url, limit):
        stream = BytesIO()
        Image.new("RGB", (240, 135), "red" if "/a/" in url else "blue").save(stream, "PNG")
        return stream.getvalue()

    monkeypatch.setattr(services, "fetch_bytes", image_bytes)
    events = Queue()
    background = services.BackgroundServices(tmp_path, events)
    try:
        background.thumbnail("a", "https://images.example/a/same-thumbnail-suffix.png")
        background.thumbnail("b", "https://images.example/b/same-thumbnail-suffix.png")
        images = {}
        for _ in range(2):
            kind, (key, image) = events.get(timeout=3)
            assert kind == "thumbnail"
            images[key] = image
        assert images["a"].getpixel((0, 0)) != images["b"].getpixel((0, 0))
        assert len(list(background.cache.glob("*.jpg"))) == 2
    finally:
        background.close()


def test_missing_history_file_is_reported_before_launching_program(tmp_path):
    with pytest.raises(FileNotFoundError, match="movido ou excluído"):
        services.open_path(str(tmp_path / "missing.mp4"))
