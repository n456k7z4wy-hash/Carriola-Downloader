from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit
from uuid import uuid4

ACTIVE = {"queued", "running", "cancelling"}
RETRYABLE = {"failed", "cancelled", "interrupted", "partial"}
HOSTS = {"youtube.com", "youtu.be", "instagram.com", "twitter.com", "x.com"}


def validate_url(value: str) -> str:
    value = value.strip()
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError("Cole um único link válido por download.")
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        port = url.port
    except ValueError as exc:
        raise ValueError("O link informado é inválido.") from exc
    if (
        url.scheme not in {"http", "https"}
        or not any(host == root or host.endswith("." + root) for root in HOSTS)
        or url.username is not None
        or url.password is not None
        or port not in {None, 80, 443}
        or not url.path.strip("/")
    ):
        raise ValueError("Use um link de vídeo ou playlist do YouTube, Instagram ou X.")
    return urlunsplit(("https", host, url.path, url.query, ""))


def playlist_kind(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None  # The user may still be typing an incomplete URL.
    if not (parsed.hostname == "youtu.be" or (parsed.hostname or "").endswith("youtube.com")):
        return None
    query = parse_qs(parsed.query)
    if not query.get("list"):
        return None
    return "playlist" if parsed.path.rstrip("/") == "/playlist" else "video"


@dataclass
class Job:
    url: str
    destination: str
    mode: str = "video"
    codec: str = "mp3"
    container: str = "mp4"
    quality: int = 0
    playlist: bool = False
    id: str = field(default_factory=lambda: uuid4().hex)
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    state: str = "queued"
    title: str = "Aguardando análise do link"
    message: str = "Na fila"
    error: str = ""
    progress: float = 0.0
    files: list[dict] = field(default_factory=list)

    def validate(self):
        self.url = validate_url(self.url)
        if self.mode not in {"video", "audio"} or self.codec not in {"mp3", "wav", "m4a"}:
            raise ValueError("Formato de áudio inválido.")
        if self.container not in {"mp4", "mkv"} or self.quality not in {
            0,
            480,
            720,
            1080,
            1440,
            2160,
        }:
            raise ValueError("Qualidade ou formato de vídeo inválido.")
        if not self.destination.strip():
            raise ValueError("Escolha uma pasta de destino.")
        self.destination = str(Path(self.destination).expanduser().resolve())

    def snapshot(self) -> dict:
        return asdict(self)

    def signature(self) -> tuple:
        return (
            self.url,
            self.destination,
            self.mode,
            self.codec,
            self.container,
            self.quality,
            self.playlist,
        )
