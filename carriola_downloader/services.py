import hashlib
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from packaging.version import Version
from PIL import Image, ImageOps

from . import REPO_URL

logger = logging.getLogger("Carriola")


def setup_logging(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            directory / "carriola.log", maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)


def fetch_bytes(url: str, limit: int) -> bytes:
    request = Request(url, headers={"User-Agent": "CarriolaDownloader", "Accept": "*/*"})
    with urlopen(request, timeout=10) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Resposta maior que o limite permitido.")
    return content


def published_release() -> dict:
    data = json.loads(
        fetch_bytes(
            "https://api.github.com/repos/n456k7z4wy-hash/Carriola-Downloader/releases/latest",
            1024 * 1024,
        )
    )
    tag = data["tag_name"]
    Version(tag.removeprefix("v"))
    url = data["html_url"]
    if not url.startswith(REPO_URL + "/releases/tag/"):
        raise ValueError("O GitHub retornou um endereço de atualização inesperado.")
    # Only link to the release. Never delete/replace sys.executable or run installers.
    return {"tag": tag, "url": url}


def open_path(value: str, *, reveal=False):
    path = Path(value).resolve()
    if not path.exists():
        raise FileNotFoundError("O arquivo foi movido ou excluído. Confira a pasta de destino.")
    if sys.platform == "win32":
        if reveal and path.is_file():
            subprocess.Popen(["explorer.exe", "/select,", str(path)])
        else:
            os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if reveal else ["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent if reveal and path.is_file() else path)])


def notify(title: str, message: str):
    if sys.platform != "win32":
        return
    try:
        from plyer import notification

        notification.notify(title=title, message=message[:240], app_name="Carriola", timeout=4)
    except Exception:
        logger.warning("Notificação indisponível", exc_info=True)


class BackgroundServices:
    """Worker results return through a Queue; only the UI creates CTkImage instances."""

    def __init__(self, directory: Path, events):
        self.cache = directory / "thumbnails"
        self.cache.mkdir(exist_ok=True)
        self.events = events
        self.closed = False
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="CarriolaAssets")
        self.pool.submit(self.clean_cache)

    def clean_cache(self):
        try:
            files = sorted(
                self.cache.glob("*.jpg"), key=lambda file: file.stat().st_mtime, reverse=True
            )
            used = 0
            for file in files:
                used += file.stat().st_size
                if used > 64 * 1024 * 1024 or time.time() - file.stat().st_mtime > 7 * 86400:
                    file.unlink(missing_ok=True)
        except OSError:
            logger.debug("Cache ocupado; limpeza adiada")

    def thumbnail(self, key: str, url: str):
        if not self.closed:
            self.pool.submit(self._thumbnail, key, url)

    def _thumbnail(self, key: str, url: str):
        if not url.startswith("https://"):
            return
        try:
            path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".jpg")
            image = None
            if path.exists():
                try:
                    with Image.open(path) as source:
                        image = source.copy()
                except (OSError, ValueError):
                    path.unlink(missing_ok=True)
            if image is None:
                with Image.open(BytesIO(fetch_bytes(url, 5 * 1024 * 1024))) as source:
                    image = ImageOps.fit(
                        source.convert("RGB"), (224, 126), Image.Resampling.LANCZOS
                    )
                image.save(path, "JPEG", quality=85)
            self.events.put(("thumbnail", (key, image)))
        except Exception:
            logger.debug("Miniatura indisponível", exc_info=True)

    def check_release(self):
        if self.closed:
            return

        def work():
            try:
                self.events.put(("release", published_release()))
            except Exception:
                logger.warning("Falha ao consultar releases", exc_info=True)
                self.events.put(
                    (
                        "error",
                        "Não foi possível consultar as versões. Confira a conexão e tente novamente.",
                    )
                )

        self.pool.submit(work)

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
