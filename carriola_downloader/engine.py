"""yt-dlp adapter. No Tkinter objects or callbacks are used here."""

import logging
import math
import os
import shutil
import sys
import time
from pathlib import Path
from threading import Event

import yt_dlp
from yt_dlp.postprocessor.common import PostProcessor

from .models import Job

logger = logging.getLogger("Carriola")


class Cancelled(Exception):
    pass


def detect_binary(name: str, explicit: str = "") -> str | None:
    executable = name + (".exe" if sys.platform == "win32" else "")
    roots = [Path(sys.executable).parent, Path(__file__).resolve().parent.parent]
    if getattr(sys, "frozen", False):
        roots.insert(0, Path(getattr(sys, "_MEIPASS", roots[0])))
    candidates = [Path(explicit)] if explicit else []
    for root in roots:
        candidates.extend(
            [
                root / executable,
                root / "tools" / name / executable,
                root / "tools" / name / "bin" / executable,
            ]
        )
    if name in {"ffmpeg", "ffprobe"}:
        if explicit:
            candidates.append(Path(explicit).parent / executable)
        candidates.extend([Path(r"C:\ffmpeg\bin") / executable])
    for path in candidates:
        if path.is_file() and (sys.platform == "win32" or os.access(path, os.X_OK)):
            return str(path.resolve())
    return shutil.which(name)


def finite_number(value) -> float:
    try:
        number = float(value)
        return max(0, number) if math.isfinite(number) else 0
    except (ValueError, TypeError):
        return 0


def format_bytes(value) -> str:
    size = finite_number(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024


def format_time(value) -> str:
    if value is None:
        return "--:--"
    minutes, seconds = divmod(int(finite_number(value)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def video_selector(quality: int, container: str):
    """Keep both audio and video; use both dimensions for portrait/ultrawide sources."""

    def select(context):
        formats = context.get("formats", [])  # yt-dlp has already sorted these.

        def fits(fmt):
            if not quality:
                return True
            width, height = finite_number(fmt.get("width")), finite_number(fmt.get("height"))
            if not width or not height:
                return False  # A requested limit cannot be verified without dimensions.
            short, long = sorted((width, height))
            long_limit = 4096 if quality == 2160 else quality * 16 / 9
            return short <= quality and long <= long_limit

        videos = [fmt for fmt in formats if fmt.get("vcodec") not in {None, "none"} and fits(fmt)]
        if not videos:
            raise yt_dlp.utils.DownloadError(
                "Nenhum vídeo disponível dentro da qualidade escolhida."
            )
        video = videos[-1]
        if video.get("acodec") not in {None, "none"}:
            yield video
            return
        audios = [
            fmt
            for fmt in formats
            if fmt.get("acodec") not in {None, "none"} and fmt.get("vcodec") == "none"
        ]
        if not audios:
            raise yt_dlp.utils.DownloadError(
                "Não foi encontrada uma faixa de áudio para este vídeo."
            )
        compatible = [fmt for fmt in audios if fmt.get("ext") == "m4a"]
        audio = (compatible or audios)[-1] if container == "mp4" else audios[-1]
        yield {
            "format_id": f"{video['format_id']}+{audio['format_id']}",
            "ext": container,
            "requested_formats": [video, audio],
            "protocol": f"{video.get('protocol', 'https')}+{audio.get('protocol', 'https')}",
        }

    return select


def friendly_error(error: str) -> str:
    lowered = error.lower()
    if "ffmpeg" in lowered or "ffprobe" in lowered:
        return "Confira o FFmpeg/FFprobe em Configurações. Eles unem o vídeo ao áudio."
    if any(term in lowered for term in ("sign in", "login", "age", "cookies", "private")):
        return "Este conteúdo exige acesso à conta ou tem restrição de idade/privacidade."
    if "unavailable" in lowered or "removed" in lowered:
        return "O conteúdo foi removido ou está indisponível."
    if "429" in lowered:
        return "A plataforma limitou as solicitações. Aguarde e tente novamente."
    if "403" in lowered or "javascript" in lowered or "signature" in lowered:
        return "A plataforma recusou o acesso. Confira o motor yt-dlp e o Deno em Configurações."
    if any(term in lowered for term in ("timed out", "connection", "network")):
        return "A conexão falhou. Confira a internet e tente novamente."
    if "permission" in lowered or "access is denied" in lowered:
        return "Sem permissão para salvar nessa pasta. Escolha outro destino."
    if "space" in lowered:
        return "Não há espaço suficiente na pasta de destino."
    return error.removeprefix("ERROR: ").strip()[:240] or "Não foi possível concluir o download."


class DownloadEngine:
    def __init__(self, ffmpeg: str, deno: str | None = None):
        self.ffmpeg = ffmpeg
        self.deno = deno

    def options(self, job, hook, post_hook, log):
        # Include the media ID and selected profile to avoid title/quality collisions.
        profile = f"{job.quality or 'best'}-{job.container}" if job.mode == "video" else job.codec
        filename = f"%(title).150B [%(id)s] [{profile}].%(ext)s"
        template = str(Path(job.destination) / filename)
        if job.playlist:
            template = str(
                Path(job.destination)
                / "%(playlist_title,playlist_id|Playlist).100B"
                / ("%(playlist_index)03d - " + filename)
            )
        # Escape literal % in the user-selected directory only.
        template = job.destination.replace("%", "%%") + template[len(job.destination) :]
        options = {
            "quiet": True,
            "noprogress": True,
            "no_color": True,
            "logger": log,
            "noplaylist": not job.playlist,
            "ignoreerrors": job.playlist,
            "outtmpl": template,
            "windowsfilenames": True,
            "continuedl": True,
            "overwrites": False,
            "final_ext": job.container if job.mode == "video" else job.codec,
            "ffmpeg_location": self.ffmpeg,
            "progress_hooks": [hook],
            "postprocessor_hooks": [post_hook],
            "concurrent_fragment_downloads": 4,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 2,
            "socket_timeout": 15,
            "postprocessors": [],
        }
        if self.deno:
            options["js_runtimes"] = {"deno": {"path": self.deno}}
        if job.mode == "video":
            options["format"] = video_selector(job.quality, job.container)
            options["merge_output_format"] = job.container
            # A single progressive source also needs remuxing if its extension differs.
            options["postprocessors"] = [
                {"key": "FFmpegVideoRemuxer", "preferedformat": job.container},
                {"key": "FFmpegMetadata", "add_metadata": True},
            ]
        else:
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": job.codec,
                    "preferredquality": "320",
                },
                {"key": "FFmpegMetadata", "add_metadata": True},
            ]
            # WAV does not support the thumbnail embedding used by yt-dlp.
            if job.codec in {"mp3", "m4a"}:
                options["writethumbnail"] = True
                options["postprocessors"].append({"key": "EmbedThumbnail"})
        return options

    def run(self, job: Job, cancel: Event, emit):
        errors = []
        completed = []
        last_progress = 0

        def check_cancel():
            if cancel.is_set():
                raise Cancelled()

        def hook(data):
            nonlocal last_progress
            check_cancel()
            now = time.monotonic()
            if data["status"] == "downloading" and now - last_progress >= 0.15:
                last_progress = now
                info = data.get("info_dict") or {}
                total = finite_number(data.get("total_bytes") or data.get("total_bytes_estimate"))
                downloaded = finite_number(data.get("downloaded_bytes"))
                progress = min(0.99, downloaded / total) if total else 0
                prefix = ""
                if info.get("playlist_index"):
                    prefix = f"Item {info['playlist_index']}/{info.get('playlist_count') or '?'} · "
                message = (
                    f"{prefix}{format_bytes(downloaded)} / {format_bytes(total) if total else '?'}"
                    f" · {format_bytes(data.get('speed'))}/s · {format_time(data.get('eta'))}"
                )
                emit(
                    "progress",
                    {
                        "progress": progress,
                        "message": message,
                        "title": info.get("title") or job.title,
                    },
                )
            elif data["status"] == "finished":
                emit("progress", {"progress": 0.99, "message": "Preparando arquivo final…"})

        def post_hook(data):
            check_cancel()
            if data["status"] == "started":
                emit("progress", {"message": "Unindo vídeo e áudio / processando arquivo…"})

        class Log:
            def debug(self, message):
                logger.debug(message)

            def warning(self, message):
                logger.warning(message)

            def error(self, message):
                errors.append(str(message))
                logger.error(message)

        class CaptureFile(PostProcessor):
            def run(self, info):
                # Runs after MoveFilesAfterDownloadPP: this is the real final filename.
                path = Path(info["filepath"])
                if path.is_file():
                    item = {
                        "path": str(path.resolve()),
                        "title": info.get("title") or path.stem,
                        "thumbnail": info.get("thumbnail") or "",
                    }
                    completed.append(item)
                    emit("file", item)
                return [], info

        check_cancel()
        Path(job.destination).mkdir(parents=True, exist_ok=True)
        options = self.options(job, hook, post_hook, Log())

        def match_filter(info, *, incomplete=False):
            check_cancel()
            return None

        options["match_filter"] = match_filter
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.add_post_processor(CaptureFile(ydl), when="after_move")
            info = ydl.extract_info(job.url, download=True)
        check_cancel()
        if not completed:
            raise RuntimeError(errors[-1] if errors else "Nenhum arquivo foi salvo.")
        if info and info.get("entries") and any(item is None for item in info["entries"]):
            errors.append("Alguns itens da playlist não puderam ser baixados.")
        return errors
