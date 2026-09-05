"""Dark desktop UI. Every widget access stays on the Tk main thread."""

import webbrowser
from pathlib import Path
from queue import Empty
from tkinter import filedialog, messagebox

import customtkinter as ctk
import yt_dlp.version

from . import REPO_URL, __version__
from .engine import DownloadEngine, detect_binary
from .models import ACTIVE, RETRYABLE, Job, playlist_kind, validate_url
from .queue_manager import DownloadQueue
from .services import BackgroundServices, notify, open_path, setup_logging
from .storage import Store, data_directory

BG, PANEL, SURFACE = "#0e1116", "#171c24", "#202733"
TEXT, MUTED, ACCENT = "#f2f4f8", "#9aa7b8", "#ee5265"
GREEN, AMBER = "#64d4a0", "#e6ba6e"
QUALITIES = {
    "Melhor disponível": 0,
    "Até 4K": 2160,
    "Até 1440p": 1440,
    "Até 1080p": 1080,
    "Até 720p": 720,
    "Até 480p": 480,
}
STATES = {
    "queued": "NA FILA",
    "running": "BAIXANDO",
    "cancelling": "CANCELANDO",
    "completed": "CONCLUÍDO",
    "partial": "PARCIAL",
    "failed": "FALHOU",
    "cancelled": "CANCELADO",
    "interrupted": "INTERROMPIDO",
}


class CarriolaApp(ctk.CTk):
    def __init__(self, directory=None, engine=None):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        super().__init__(fg_color=BG)
        self.title("Carriola Vídeos Downloader · Desenvolvimento")
        self.geometry("1100x830")
        self.minsize(900, 650)
        self.directory = Path(directory) if directory else data_directory()
        setup_logging(self.directory)
        self.store = Store(self.directory)
        self.store.import_legacy_config(
            Path(__file__).resolve().parent.parent / "carriola_config.ini"
        )
        ffmpeg = detect_binary("ffmpeg", self.store.get("ffmpeg", ""))
        deno = detect_binary("deno")
        self.engine = engine or DownloadEngine(ffmpeg, deno)
        self.downloads = DownloadQueue(self.store, self.engine)
        self.services = BackgroundServices(self.directory, self.downloads.events)
        self.cards = {}
        self._closing = False
        self._compact = False
        self._settings = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build_ui()
        for job in self.downloads.snapshots():
            self.render_job(job, initial=True)
        self.refresh_count()
        self.after(80, self.poll_events)

    def button(self, parent, text, command, **kwargs):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            corner_radius=8,
            fg_color=kwargs.pop("fg_color", SURFACE),
            hover_color="#354153",
            text_color=TEXT,
            **kwargs,
        )

    def build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(22, 16))
        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left")
        ctk.CTkLabel(brand, text="carriola", font=("Segoe UI", 30, "bold"), text_color=TEXT).pack(
            anchor="w"
        )
        ctk.CTkLabel(
            brand, text="VÍDEOS E ÁUDIO, DO SEU JEITO", font=("Segoe UI", 10), text_color=MUTED
        ).pack(anchor="w")
        self.button(header, "Preferências", self.show_settings, width=115).pack(
            side="right", padx=(10, 0)
        )
        self.button(header, "Compacto", self.toggle_compact, width=95).pack(side="right")
        self.engine_label = ctk.CTkLabel(
            header,
            text="Motor pronto" if self.engine.ffmpeg else "Configure o FFmpeg",
            text_color=GREEN if self.engine.ffmpeg else AMBER,
        )
        self.engine_label.pack(side="right", padx=16)

        composer = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=16)
        composer.pack(fill="x", padx=28)
        ctk.CTkLabel(composer, text="O que vamos baixar?", font=("Segoe UI", 19, "bold")).pack(
            anchor="w", padx=20, pady=(15, 5)
        )
        url_row = ctk.CTkFrame(composer, fg_color="transparent")
        url_row.pack(fill="x", padx=20, pady=(5, 10))
        self.url = ctk.StringVar()
        self.entry = ctk.CTkEntry(
            url_row,
            textvariable=self.url,
            placeholder_text="Cole o link do YouTube, Instagram ou X",
            height=43,
            fg_color=BG,
            border_color="#303b4b",
        )
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda event: self.add_download())
        self.button(url_row, "Colar link", self.paste_link, width=100, height=43).pack(
            side="left", padx=(8, 0)
        )
        self.url.trace_add("write", self.update_playlist)

        options = ctk.CTkFrame(composer, fg_color="transparent")
        options.pack(fill="x", padx=20, pady=(0, 10))
        self.mode = ctk.CTkSegmentedButton(
            options,
            values=["Vídeo", "Áudio"],
            command=self.update_mode,
            selected_color=ACCENT,
            selected_hover_color="#c94153",
            height=34,
        )
        self.mode.set(self.store.get("mode", "Vídeo"))
        self.mode.pack(side="left", padx=(0, 12))
        self.quality = ctk.CTkOptionMenu(
            options, values=list(QUALITIES), width=165, fg_color=SURFACE, button_color=SURFACE
        )
        self.quality.set(self.store.get("quality", "Melhor disponível"))
        self.quality.pack(side="left", padx=(0, 8))
        self.format = ctk.CTkOptionMenu(
            options, values=["MP4", "MKV"], width=90, fg_color=SURFACE, button_color=SURFACE
        )
        self.format.pack(side="left")
        self.playlist_value = ctk.BooleanVar(value=False)
        self.playlist_toggle = ctk.CTkCheckBox(
            options,
            text="Playlist completa",
            variable=self.playlist_value,
            fg_color=ACCENT,
            width=150,
        )
        self.update_mode(self.mode.get())

        folder = ctk.CTkFrame(composer, fg_color="transparent")
        folder.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkLabel(folder, text="Salvar em", text_color=MUTED, width=75, anchor="w").pack(
            side="left"
        )
        self.destination = ctk.StringVar(
            value=self.store.get("download_path", str(Path.home() / "Downloads"))
        )
        ctk.CTkEntry(
            folder, textvariable=self.destination, height=32, fg_color=BG, border_width=0
        ).pack(side="left", fill="x", expand=True)
        self.button(folder, "Escolher pasta", self.browse, width=120, height=32).pack(
            side="left", padx=(8, 0)
        )
        action = ctk.CTkFrame(composer, fg_color="transparent")
        action.pack(fill="x", padx=20, pady=(0, 16))
        self.tip = ctk.CTkLabel(
            action,
            text="Qualidade original • Vídeo com áudio • Fila automática",
            text_color=MUTED,
            font=("Segoe UI", 11),
        )
        self.tip.pack(side="left")
        self.add_button = self.button(
            action, "+  Adicionar à fila", self.add_download, width=200, height=40, fg_color=ACCENT
        )
        self.add_button.pack(side="right")

        self.notice = ctk.CTkLabel(self, text="", text_color=AMBER, height=26, anchor="w")
        self.notice.pack(fill="x", padx=30, pady=(3, 0))
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=28, pady=(4, 8))
        self.count = ctk.CTkLabel(bar, text="Seus downloads", font=("Segoe UI", 17, "bold"))
        self.count.pack(side="left")
        self.button(bar, "Limpar histórico", self.clear_history, width=130).pack(side="right")
        self.search = ctk.CTkEntry(
            bar, placeholder_text="Buscar no histórico", width=210, fg_color=PANEL, border_width=0
        )
        self.search.pack(side="right", padx=10)
        self.search.bind("<KeyRelease>", self.filter_cards)
        self.scroll = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        self.scroll.pack(fill="both", expand=True, padx=20, pady=(0, 5))
        self.empty = ctk.CTkLabel(
            self.scroll,
            text="Sua próxima ideia começa com um link.\nCole um vídeo acima para começar.",
            text_color=MUTED,
            font=("Segoe UI", 15),
            height=145,
        )
        self.empty.pack(fill="x")
        ctk.CTkLabel(
            self,
            text=f"v{__version__} · Versão de desenvolvimento",
            text_color=MUTED,
            font=("Segoe UI", 10),
            height=24,
        ).pack(fill="x", pady=(0, 6))
        self.entry.focus_set()

    def update_mode(self, mode):
        video = mode == "Vídeo"
        self.quality.configure(state="normal" if video else "disabled")
        self.format.configure(values=["MP4", "MKV"] if video else ["MP3", "WAV", "M4A"])
        self.format.set(
            self.store.get("video_format", "MP4")
            if video
            else self.store.get("audio_format", "MP3")
        )

    def update_playlist(self, *_):
        kind = playlist_kind(self.url.get().strip())
        if kind:
            self.playlist_toggle.pack(side="right")
            if kind == "playlist":
                self.playlist_value.set(True)
            self.playlist_toggle.configure(state="disabled" if kind == "playlist" else "normal")
        else:
            self.playlist_toggle.pack_forget()
            self.playlist_value.set(False)

    def paste_link(self):
        try:
            self.url.set(self.clipboard_get().strip())
        except Exception:
            self.notice.configure(text="A área de transferência não contém um link.")

    def browse(self):
        folder = filedialog.askdirectory(parent=self, title="Escolher pasta de downloads")
        if folder:
            self.destination.set(folder)
            self.store.set("download_path", folder)

    def add_download(self):
        if self._closing:
            return
        try:
            url = validate_url(self.url.get())
            if not self.engine.ffmpeg:
                raise ValueError("Abra Preferências e configure o FFmpeg para começar.")
            video = self.mode.get() == "Vídeo"
            job = Job(
                url=url,
                destination=self.destination.get(),
                mode="video" if video else "audio",
                codec=self.format.get().lower() if not video else "mp3",
                container=self.format.get().lower() if video else "mp4",
                quality=QUALITIES[self.quality.get()] if video else 0,
                playlist=bool(playlist_kind(url)) and self.playlist_value.get(),
            )
            self.downloads.submit(job)
            for key, value in {
                "download_path": job.destination,
                "mode": self.mode.get(),
                "quality": self.quality.get(),
                "video_format" if video else "audio_format": self.format.get(),
            }.items():
                self.store.set(key, value)
            self.url.set("")
            self.notice.configure(
                text="Download adicionado. Você já pode colocar outro link na fila.",
                text_color=GREEN,
            )
        except (ValueError, OSError, KeyError) as exc:
            self.notice.configure(text=str(exc), text_color=AMBER)

    def render_job(self, job, initial=False):
        key = job["id"]
        if key not in self.cards:
            self.empty.pack_forget()
            frame = ctk.CTkFrame(self.scroll, fg_color=PANEL, corner_radius=12)
            frame.pack(fill="x", padx=6, pady=5)
            frame.grid_columnconfigure(1, weight=1)
            image = ctk.CTkLabel(
                frame,
                text="ÁUDIO" if job["mode"] == "audio" else "VÍDEO",
                width=112,
                height=63,
                fg_color=SURFACE,
                corner_radius=8,
                text_color=MUTED,
            )
            image.grid(row=0, column=0, rowspan=3, padx=14, pady=14)
            title = ctk.CTkLabel(
                frame, text="", anchor="w", width=1, wraplength=500, font=("Segoe UI", 13, "bold")
            )
            title.grid(row=0, column=1, sticky="ew", pady=(10, 0))
            status = ctk.CTkLabel(
                frame,
                text="",
                anchor="w",
                width=1,
                wraplength=500,
                text_color=MUTED,
                font=("Segoe UI", 10),
            )
            status.grid(row=1, column=1, sticky="ew")
            progress = ctk.CTkProgressBar(frame, height=4, progress_color=ACCENT, fg_color=SURFACE)
            progress.grid(row=2, column=1, sticky="ew", pady=(2, 12))
            actions = ctk.CTkFrame(frame, fg_color="transparent", width=150)
            actions.grid(row=0, column=2, rowspan=3, padx=14, pady=10)
            primary = self.button(actions, "", lambda: self.job_action(key), width=115, height=28)
            primary.pack(pady=2)
            secondary = self.button(
                actions, "Detalhes", lambda: self.show_details(key), width=115, height=26
            )
            secondary.pack(pady=2)
            self.cards[key] = {
                "frame": frame,
                "title": title,
                "status": status,
                "progress": progress,
                "image": image,
                "primary": primary,
                "data": job,
                "thumb": "",
                "state": None,
            }
            frame.bind(
                "<Configure>",
                lambda event, title=title, status=status: (
                    title.configure(wraplength=max(220, event.width - 310)),
                    status.configure(wraplength=max(220, event.width - 310)),
                ),
            )
        card = self.cards[key]
        previous = card["state"]
        card["data"], card["state"] = job, job["state"]
        color = (
            GREEN if job["state"] == "completed" else AMBER if job["state"] in RETRYABLE else MUTED
        )
        title_text = job["title"] if job["title"] != "Aguardando análise do link" else job["url"]
        card["title"].configure(text=title_text[:72])
        card["status"].configure(
            text=f"{STATES[job['state']]} · {job['message']}"[:112], text_color=color
        )
        card["progress"].set(job["progress"])
        primary_text = (
            "Cancelar"
            if job["state"] in ACTIVE
            else "Tentar novamente"
            if job["state"] in RETRYABLE
            else "Abrir pasta"
            if job["playlist"]
            else "Abrir arquivo"
        )
        card["primary"].configure(
            text=primary_text, state="disabled" if job["state"] == "cancelling" else "normal"
        )
        if job["files"]:
            thumb = job["files"][-1].get("thumbnail", "")
            if thumb and thumb != card["thumb"] and not self._closing:
                card["thumb"] = thumb
                self.services.thumbnail(key, thumb)
        if (
            not self._closing
            and not initial
            and previous in ACTIVE
            and job["state"] == "completed"
            and self.store.get("notifications", True)
        ):
            self.services.pool.submit(notify, "Download concluído", job["title"])
        self.refresh_count()
        self.filter_cards()

    def refresh_count(self):
        active = sum(card["data"]["state"] in ACTIVE for card in self.cards.values())
        self.count.configure(
            text=f"Seus downloads · {active} na fila"
            if active
            else f"Seus downloads · {len(self.cards)}"
        )

    def job_action(self, key):
        job = self.cards[key]["data"]
        try:
            if job["state"] in ACTIVE:
                self.downloads.cancel(key)
            elif job["state"] in RETRYABLE:
                self.downloads.retry(key)
            elif job["files"]:
                self.open_item(job["files"][0]["path"], reveal=job["playlist"])
        except (ValueError, OSError) as exc:
            self.notice.configure(text=str(exc), text_color=AMBER)

    def open_item(self, path, reveal=False):
        try:
            open_path(path, reveal=reveal)
        except OSError as exc:
            self.notice.configure(text=str(exc), text_color=AMBER)

    def filter_cards(self, *_):
        term = self.search.get().casefold()
        for card in self.cards.values():
            job = card["data"]
            matches = (
                term in (job["title"] + " " + job["url"] + " " + STATES[job["state"]]).casefold()
            )
            visible = matches and (not self._compact or job["state"] in ACTIVE)
            if visible:
                card["frame"].pack(fill="x", padx=6, pady=5)
            else:
                card["frame"].pack_forget()

    def clear_history(self):
        if messagebox.askyesno(
            "Limpar histórico",
            "Remover da lista os downloads finalizados?\nOs arquivos salvos serão mantidos.",
            parent=self,
        ):
            for key in self.downloads.clear_finished():
                if key in self.cards:
                    self.cards.pop(key)["frame"].destroy()
            self.refresh_count()
            if not self.cards:
                self.empty.pack(fill="x")

    def toggle_compact(self):
        self._compact = not self._compact
        self.geometry("900x650" if self._compact else "1100x830")
        self.filter_cards()

    def show_details(self, key):
        job = self.cards[key]["data"]
        window = ctk.CTkToplevel(self, fg_color=BG)
        window.title("Detalhes do download")
        window.geometry("740x460")
        window.transient(self)
        text = ctk.CTkTextbox(window, fg_color=PANEL, wrap="word")
        text.pack(fill="both", expand=True, padx=18, pady=18)
        details = (
            f"{job['title']}\n{job['url']}\n\n{STATES[job['state']]}\n{job['message']}\n\n"
            + "Arquivos salvos:\n"
            + "\n".join(item["path"] for item in job["files"])
        )
        if job["error"]:
            details += "\n\nDetalhes técnicos:\n" + job["error"]
        text.insert("1.0", details)
        text.configure(state="disabled")
        self.button(
            window, "Abrir pasta de destino", lambda: self.open_item(job["destination"])
        ).pack(pady=(0, 18))

    def show_settings(self):
        if self._settings is not None and self._settings.winfo_exists():
            self._settings.focus()
            return
        window = self._settings = ctk.CTkToplevel(self, fg_color=BG)
        window.title("Preferências")
        window.geometry("650x460")
        window.transient(self)
        ctk.CTkLabel(window, text="Preferências", font=("Segoe UI", 22, "bold")).pack(
            anchor="w", padx=24, pady=(20, 12)
        )
        status = ctk.CTkLabel(
            window, text="", justify="left", wraplength=600, anchor="w", text_color=MUTED
        )
        status.pack(fill="x", padx=24)

        def refresh():
            status.configure(
                text=f"FFmpeg: {self.engine.ffmpeg or 'Não encontrado'}\n"
                f"Deno: {self.engine.deno or 'Não encontrado — recomendado para YouTube'}\n"
                f"yt-dlp: {yt_dlp.version.__version__}\n\n"
                "O FFmpeg precisa estar na mesma pasta do FFprobe.\n"
                "Para YouTube, instale também o Deno e mantenha o motor atualizado."
            )

        def choose_ffmpeg():
            path = filedialog.askopenfilename(parent=window, title="Selecione ffmpeg.exe")
            if path:
                sibling = Path(path).with_name(
                    "ffprobe.exe" if Path(path).suffix.lower() == ".exe" else "ffprobe"
                )
                if Path(path).stem.lower() != "ffmpeg" or not sibling.is_file():
                    messagebox.showerror(
                        "FFmpeg",
                        "Selecione o FFmpeg em uma pasta que também tenha o FFprobe.",
                        parent=window,
                    )
                    return
                self.engine.ffmpeg = path
                self.store.set("ffmpeg", path)
                self.engine_label.configure(text="Motor pronto", text_color=GREEN)
                refresh()

        refresh()
        row = ctk.CTkFrame(window, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=14)
        self.button(row, "Localizar FFmpeg", choose_ffmpeg, width=155).pack(
            side="left", padx=(0, 10)
        )
        self.button(
            row,
            "Instruções de instalação",
            lambda: webbrowser.open(REPO_URL + "#executar-a-versão-de-desenvolvimento"),
            width=185,
        ).pack(side="left")
        enabled = ctk.BooleanVar(value=self.store.get("notifications", True))
        ctk.CTkCheckBox(
            window,
            text="Notificação do Windows ao concluir",
            variable=enabled,
            command=lambda: self.store.set("notifications", enabled.get()),
            fg_color=ACCENT,
        ).pack(anchor="w", padx=24, pady=8)
        self.button(
            window, "Consultar versão publicada", self.services.check_release, width=235
        ).pack(anchor="w", padx=24, pady=8)
        self.button(
            window, "Abrir pasta de logs", lambda: self.open_item(str(self.directory)), width=235
        ).pack(anchor="w", padx=24, pady=8)

    def poll_events(self):
        for _ in range(100):
            try:
                kind, data = self.downloads.events.get_nowait()
            except Empty:
                break
            if kind == "job":
                # A stale completion event must not resurrect a history row just cleared.
                if data["id"] in self.downloads.jobs:
                    self.render_job(data)
            elif kind == "thumbnail" and data[0] in self.cards:
                image = ctk.CTkImage(light_image=data[1], dark_image=data[1], size=(112, 63))
                self.cards[data[0]]["image"].configure(image=image, text="")
            elif kind == "error":
                self.notice.configure(text=data, text_color=AMBER)
            elif kind == "release" and not self._closing:
                if messagebox.askyesno(
                    "Versão publicada",
                    f"A versão publicada é {data['tag']}.\n"
                    "Você está usando uma versão de desenvolvimento.\n\nAbrir a página dessa versão?",
                    parent=self,
                ):
                    webbrowser.open(data["url"])
        if self._closing and not self.downloads.is_alive():
            self.destroy()
            return
        self.after(80, self.poll_events)

    def on_close(self):
        if self._closing:
            return
        self._closing = True
        self.add_button.configure(state="disabled")
        self.notice.configure(text="Encerrando downloads após a etapa atual…", text_color=AMBER)
        self.downloads.close()
        self.services.close()
