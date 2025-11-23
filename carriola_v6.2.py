import os
import sys
import threading
import subprocess
import logging
import logging.handlers
import time
import configparser
import shutil
import webbrowser
import json
from pathlib import Path
from typing import Optional, Callable
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

# Dependências externas (instalar via pip)
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image
import requests
import yt_dlp
import yt_dlp.utils
from packaging import version  # pip install packaging

# --------------------- Notificações ---------------------
try:
    from plyer import notification
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

# --------------------- Logging ---------------------
def setup_logging():
    logger = logging.getLogger("Carriola")
    logger.setLevel(logging.INFO)
    if logger.handlers: return logger
    
    file_handler = logging.handlers.RotatingFileHandler(
        "carriola_downloader.log", maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'
    )
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] - %(message)s", "%H:%M:%S")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger

logger = setup_logging()

# --------------------- Sistema de Auto-Update (NOVO) ---------------------
class AutoUpdater:
    def __init__(self, current_version, repo_url):
        self.current_version = current_version
        # Transforma https://github.com/user/repo em api url
        if repo_url.endswith("/"): repo_url = repo_url[:-1]
        self.repo_api = repo_url.replace("github.com/", "api.github.com/repos/") + "/releases/latest"
        self.download_url = ""
        self.new_version = ""

    def check_for_updates(self):
        """Verifica se há uma versão (tag) maior no GitHub."""
        try:
            logger.info(f"Verificando updates em: {self.repo_api}")
            response = requests.get(self.repo_api, timeout=5)
            if response.status_code == 200:
                data = response.json()
                latest_tag = data.get('tag_name', '0.0').replace('v', '')
                
                # Compara as versões
                if version.parse(latest_tag) > version.parse(self.current_version):
                    self.new_version = latest_tag
                    # Pega o primeiro asset (espera-se que seja o .exe)
                    if 'assets' in data and len(data['assets']) > 0:
                        self.download_url = data['assets'][0]['browser_download_url']
                        return True
            return False
        except Exception as e:
            logger.error(f"Erro no AutoUpdater: {e}")
            return False

    def download_and_install(self):
        """Baixa o novo exe e cria um .bat para substituir o atual."""
        if not self.download_url: return
        
        try:
            logger.info(f"Baixando nova versão: {self.download_url}")
            r = requests.get(self.download_url, stream=True)
            new_exe_name = "Carriola_Update.exe"
            
            with open(new_exe_name, 'wb') as f:
                shutil.copyfileobj(r.raw, f)

            current_exe = sys.executable
            # Script BAT que espera, deleta o atual, renomeia o novo e reabre
            batch_script = f"""
            @echo off
            echo Atualizando Carriola...
            timeout /t 2 /nobreak > NUL
            del "{current_exe}"
            move "{new_exe_name}" "{current_exe}"
            start "" "{current_exe}"
            del "%~f0"
            """
            
            bat_path = "updater.bat"
            with open(bat_path, "w") as bat:
                bat.write(batch_script)

            logger.info("Executando BAT de atualização...")
            subprocess.Popen(bat_path, shell=True)
            sys.exit(0)
            
        except Exception as e:
            logger.error(f"Falha na instalação do update: {e}")
            messagebox.showerror("Erro Crítico", f"Falha ao atualizar: {e}")

# --------------------- Cache de Imagens ---------------------
class AsyncImageLoader:
    def __init__(self, cache_dir="cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.memory_cache = {} 

    def load_image(self, url: str, callback: Callable[[ctk.CTkImage], None], size=(120, 68)):
        if not url: return
        if url in self.memory_cache:
            callback(self.memory_cache[url])
            return
        self.executor.submit(self._process_image, url, callback, size)

    def _process_image(self, url, callback, size):
        try:
            safe_name = "".join(c for c in url if c.isalnum())[-20:] + ".png"
            file_path = self.cache_dir / safe_name
            pil_image = None
            
            if file_path.exists():
                try:
                    pil_image = Image.open(file_path)
                    pil_image.load()
                except: pass

            if not pil_image:
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    data = BytesIO(resp.content)
                    pil_image = Image.open(data)
                    with open(file_path, "wb") as f:
                        f.write(resp.content)
            
            if pil_image:
                ctk_img = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=size)
                self.memory_cache[url] = ctk_img
                callback(ctk_img)
        except Exception as e:
            logger.error(f"Erro imagem: {e}")

    def clear_old_cache(self):
        try:
            now = time.time()
            for f in self.cache_dir.glob("*.png"):
                if now - f.stat().st_mtime > 7 * 86400:
                    f.unlink()
        except: pass

# --------------------- Config & Utils ---------------------
class ConfigManager:
    def __init__(self):
        self.config_file = Path("carriola_config.ini")
        self.config = configparser.ConfigParser()
        if not self.config_file.exists():
            self.config['DEFAULT'] = {'download_path': str(Path.home() / "Downloads")}
            self.save()
        else:
            self.config.read(self.config_file)

    def get(self, key, default=None):
        return self.config.get('DEFAULT', key, fallback=default)
    
    def set(self, key, value):
        self.config['DEFAULT'][key] = str(value)
        self.save()

    def save(self):
        with open(self.config_file, 'w') as f: self.config.write(f)

def detect_ffmpeg():
    # 1. Prioridade: FFmpeg embutido no .exe (PyInstaller)
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
        bundled_ffmpeg = os.path.join(base_path, 'ffmpeg.exe')
        if os.path.exists(bundled_ffmpeg):
            return bundled_ffmpeg

    # 2. FFmpeg no PATH do sistema
    if subprocess.call("ffmpeg -version", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
        return "ffmpeg"
    
    # 3. Pasta local (desenvolvimento)
    common_paths = [r"ffmpeg.exe", r"ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"]
    for p in common_paths:
        if os.path.exists(p): return os.path.abspath(p)
    return None

def notify(title, msg):
    if not HAS_NOTIFY: return
    threading.Thread(target=lambda: notification.notify(
        title=title, message=msg, app_name="Carriola", timeout=4
    ), daemon=True).start()

# --------------------- Engine de Download (6.1) ---------------------
class Downloader:
    def __init__(self, ffmpeg):
        self.ffmpeg = ffmpeg
        self._stop = False

    def stop(self): self._stop = True
    def reset(self): self._stop = False

    def _format_bytes(self, size):
        if not size: return "0 B"
        power = 1024
        n = 0
        power_labels = {0 : '', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
        while size > power:
            size /= power
            n += 1
        return f"{size:.2f} {power_labels.get(n, '')}B"

    def _format_time(self, seconds):
        if not seconds: return "--:--"
        m, s = divmod(int(seconds), 60)
        if m > 60:
            h, m = divmod(m, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def get_opts(self, url: str, mode: str, progress_hook, process_playlist_full: bool):
        is_youtube = "youtube" in url or "youtu.be" in url
        
        opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': not process_playlist_full, 
            'progress_hooks': [progress_hook],
            'ffmpeg_location': self.ffmpeg,
            'concurrent_fragment_downloads': 4, 
            'buffersize': 1024 * 1024,
            'retries': 10,
            'addmetadata': True,
        }

        if mode == 'video':
            if is_youtube:
                opts['format'] = 'bestvideo[height<=2160]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best'
                opts['merge_output_format'] = 'mp4'
            else:
                opts['format'] = 'best'
        else: # Audio
            opts['format'] = 'bestaudio/best'
            opts['writethumbnail'] = True 
            opts['postprocessors'] = [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
                {'key': 'FFmpegMetadata', 'add_metadata': True},
                {'key': 'EmbedThumbnail'},
            ]

        return opts

    def run(self, url, path, mode, codec=None, progress_cb=None, status_cb=None, playlist_mode=False):
        self.reset()
        
        def hook(d):
            if self._stop: raise yt_dlp.utils.DownloadError("CANCELLED")
            
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes') or 0
                percent = downloaded / total if total > 0 else 0
                
                if progress_cb: progress_cb(percent)
                
                if status_cb:
                    speed_raw = d.get('speed')
                    eta_raw = d.get('eta')
                    
                    speed_str = f"{self._format_bytes(speed_raw)}/s" if speed_raw else "-- B/s"
                    eta_str = self._format_time(eta_raw) if eta_raw else "--:--"
                    total_str = self._format_bytes(total)
                    
                    info_pl = ""
                    if d.get('info_dict', {}).get('playlist_count'):
                        curr = d.get('info_dict', {}).get('playlist_index')
                        count = d.get('info_dict', {}).get('playlist_count')
                        info_pl = f"[Vídeo {curr}/{count}] "

                    status_text = f"{info_pl}📦 {total_str}  |  🚀 {speed_str}  |  ⏳ {eta_str}"
                    status_cb(status_text)

        opts = self.get_opts(url, mode, hook, playlist_mode)
        
        if playlist_mode:
            opts['outtmpl'] = os.path.join(path, '%(playlist)s', '%(playlist_index)s - %(title)s.%(ext)s')
        else:
            opts['outtmpl'] = os.path.join(path, '%(title)s.%(ext)s')

        if mode == 'audio' and codec:
             opts['postprocessors'][0]['preferredcodec'] = codec

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if 'entries' in info:
                    title = info.get('title', 'Playlist Baixada')
                    thumb = None 
                    filename = os.path.join(path, title) 
                else:
                    filename = ydl.prepare_filename(info)
                    title = info.get('title')
                    thumb = info.get('thumbnail')
                    
                    if mode == 'audio':
                        filename = os.path.splitext(filename)[0] + f".{codec}"
                    elif mode == 'video' and opts.get('merge_output_format') == 'mp4':
                        filename = os.path.splitext(filename)[0] + ".mp4"

                return filename, thumb, title
        except Exception as e:
            if "CANCELLED" in str(e): return None, None, "CANCELADO"
            raise e

# --------------------- Interface Gráfica ---------------------
class CarriolaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # ---------------- CONFIG DO UPDATE ----------------
        self.VERSION = "6.1"  # Mude isso quando lançar updates (ex: 6.2, 6.3)
        self.REPO_URL = "https://github.com/SEU_USUARIO/SEU_REPOSITORIO" # <--- COLOQUE SEU LINK AQUI
        # --------------------------------------------------

        self.ffmpeg = detect_ffmpeg()
        if not self.ffmpeg:
            messagebox.showerror("Erro Crítico", "FFmpeg não encontrado!\nO programa não pode funcionar sem ele.")
            self.destroy()
            return

        self.downloader = Downloader(self.ffmpeg)
        self.cfg = ConfigManager()
        self.img_loader = AsyncImageLoader()
        self.history_items = [] 
        self.compact_mode = False
        
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title(f"📥 Carriola Downloader {self.VERSION}")
        self.geometry("1150x820")
        self.minsize(500, 200) 
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.setup_ui()
        
        # Inicia limpeza de cache e verificação de update
        threading.Thread(target=self.img_loader.clear_old_cache, daemon=True).start()
        threading.Thread(target=self.check_update_startup, daemon=True).start()

    def check_update_startup(self):
        """Verifica atualização silenciosamente ao iniciar"""
        if "github.com/SEU_USUARIO" in self.REPO_URL:
            logger.warning("REPO_URL não configurado. Update desativado.")
            return

        updater = AutoUpdater(self.VERSION, self.REPO_URL)
        if updater.check_for_updates():
            # Usa invoke para garantir thread-safety com UI
            self.after(0, lambda: self.ask_update(updater))

    def ask_update(self, updater):
        msg = f"Uma nova versão ({updater.new_version}) está disponível!\n\nDeseja atualizar agora e reiniciar o programa?"
        if messagebox.askyesno("Atualização Disponível", msg):
            self.lbl_video_status.configure(text="⏳ Baixando atualização... Aguarde...")
            self.lbl_audio_status.configure(text="⏳ Baixando atualização... Aguarde...")
            
            # Roda o download em thread para não travar a tela enquanto baixa
            threading.Thread(target=updater.download_and_install, daemon=True).start()

    def on_close(self):
        self.downloader.stop()
        self.quit()

    def setup_ui(self):
        # --- Header ---
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.pack(fill="x", padx=12, pady=(8, 0))

        title = ctk.CTkLabel(self.top_frame, text="📥 Carriola Vídeos Downloads", font=("Helvetica", 20, "bold"))
        title.pack(side="left", padx=(6, 10), pady=6)
        
        self.btn_compact = ctk.CTkButton(self.top_frame, text="🔽 Compacto", width=80, fg_color="#555", command=self.toggle_compact)
        self.btn_compact.pack(side="right", padx=5)

        # Botão de versão (apenas informativo agora)
        ver_lbl = ctk.CTkLabel(self.top_frame, text=f"v{self.VERSION}", text_color="gray")
        ver_lbl.pack(side="right", padx=10)

        # --- Abas ---
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="x", padx=20, pady=12)
        self.tab_video = self.tabview.add("🎥 Vídeo")
        self.tab_audio = self.tabview.add("🎵 Áudio")

        self.build_tab_video()
        self.build_tab_audio()

        # --- Histórico ---
        self.hist_frame_container = ctk.CTkFrame(self)
        self.hist_frame_container.pack(fill="both", expand=True, padx=20, pady=12)

        top_hist = ctk.CTkFrame(self.hist_frame_container)
        top_hist.pack(fill="x", padx=8, pady=(8, 6))
        
        ctk.CTkLabel(top_hist, text="📁 Histórico", font=("Helvetica", 16)).pack(side="left", padx=(6,12))
        
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self.filter_history)
        ctk.CTkEntry(top_hist, textvariable=self.search_var, placeholder_text="Pesquisar...").pack(side="left", padx=6, fill="x", expand=True)
        ctk.CTkButton(top_hist, text="Limpar", fg_color="#d9534f", width=60, command=self.clear_history).pack(side="right", padx=6)

        self.scroll_hist = ctk.CTkScrollableFrame(self.hist_frame_container)
        self.scroll_hist.pack(fill="both", expand=True, padx=8, pady=(0,8))

    def toggle_compact(self):
        self.compact_mode = not self.compact_mode
        if self.compact_mode:
            self.geometry("600x350")
            self.hist_frame_container.pack_forget()
            self.btn_compact.configure(text="🔼 Expandir")
        else:
            self.geometry("1150x820")
            self.hist_frame_container.pack(fill="both", expand=True, padx=20, pady=12)
            self.btn_compact.configure(text="🔽 Compacto")

    # --- LÓGICA DE ESTILO DINÂMICO ---
    def update_btn_style(self, sv_name, *args):
        if "video" in str(sv_name).lower():
            txt = self.url_var_v.get()
            btn = self.btn_start_v
            base_text = "BAIXAR VÍDEO"
        else:
            txt = self.url_var_a.get()
            btn = self.btn_start_a
            base_text = "BAIXAR ÁUDIO"
            
        if "youtube" in txt or "youtu.be" in txt:
            btn.configure(fg_color="#CC0000", text=f"▶️ {base_text} (YouTube)", hover_color="#990000")
        elif "instagram" in txt:
            btn.configure(fg_color="#C13584", text=f"📸 {base_text} (Instagram)", hover_color="#833AB4")
        elif "twitter" in txt or "x.com" in txt:
            btn.configure(fg_color="#000000", text=f"✖️ {base_text} (X)", hover_color="#333333")
        else:
            btn.configure(fg_color="#3a6afc", text=f"⬇️ {base_text}", hover_color="#1f53bd")

    def paste_to_entry(self, mode):
        try:
            clip = self.clipboard_get()
            if mode == 'video':
                self.entry_video.delete(0, 'end')
                self.entry_video.insert(0, clip)
            else:
                self.entry_audio.delete(0, 'end')
                self.entry_audio.insert(0, clip)
        except:
            pass

    def build_tab_video(self):
        vcard = ctk.CTkFrame(self.tab_video)
        vcard.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(vcard, text="Link do Vídeo / Playlist:", font=("Helvetica", 14)).pack(anchor="w", padx=10)
        
        inp_frame = ctk.CTkFrame(vcard, fg_color="transparent")
        inp_frame.pack(fill="x", padx=10, pady=5)
        
        self.url_var_v = ctk.StringVar()
        self.url_var_v.trace_add("write", lambda n,i,m: self.update_btn_style("video", n))
        
        self.entry_video = ctk.CTkEntry(inp_frame, textvariable=self.url_var_v, placeholder_text="Cole o link aqui...")
        self.entry_video.pack(side="left", fill="x", expand=True, padx=(0,5))
        
        ctk.CTkButton(inp_frame, text="📋 Colar", width=60, fg_color="#555", command=lambda: self.paste_to_entry('video')).pack(side="right")

        line = ctk.CTkFrame(vcard)
        line.pack(fill="x", padx=10, pady=4)
        self.var_path = ctk.StringVar(value=self.cfg.get('download_path'))
        ctk.CTkEntry(line, textvariable=self.var_path).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(line, text="Procurar", width=100, command=lambda: self.browse(self.var_path)).pack(side="right", padx=6)

        btns = ctk.CTkFrame(vcard)
        btns.pack(fill="x", padx=10, pady=8)
        self.btn_start_v = ctk.CTkButton(btns, text="⬇️ BAIXAR VÍDEO", fg_color="#3a6afc", height=40, font=("Arial", 13, "bold"), 
                                       command=lambda: self.start_download('video'))
        self.btn_start_v.pack(side="left", fill="x", expand=True)
        self.btn_stop_v = ctk.CTkButton(btns, text="CANCELAR", fg_color="#FF0000", height=40, state="disabled", command=self.stop_download)
        self.btn_stop_v.pack(side="left", padx=8)

        self.prog_v = ctk.CTkProgressBar(vcard, height=10)
        self.prog_v.set(0)
        self.prog_v.pack(fill="x", padx=10)
        self.lbl_video_status = ctk.CTkLabel(vcard, text="Pronto", font=("Consolas", 12))
        self.lbl_video_status.pack(fill="x", pady=5)

    def build_tab_audio(self):
        acard = ctk.CTkFrame(self.tab_audio)
        acard.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(acard, text="Link do Áudio / Playlist:", font=("Helvetica", 14)).pack(anchor="w", padx=10)
        
        inp_frame = ctk.CTkFrame(acard, fg_color="transparent")
        inp_frame.pack(fill="x", padx=10, pady=5)
        
        self.url_var_a = ctk.StringVar()
        self.url_var_a.trace_add("write", lambda n,i,m: self.update_btn_style("audio", n))
        
        self.entry_audio = ctk.CTkEntry(inp_frame, textvariable=self.url_var_a, placeholder_text="Cole o link aqui...")
        self.entry_audio.pack(side="left", fill="x", expand=True, padx=(0,5))
        
        ctk.CTkButton(inp_frame, text="📋 Colar", width=60, fg_color="#555", command=lambda: self.paste_to_entry('audio')).pack(side="right")

        line = ctk.CTkFrame(acard)
        line.pack(fill="x", padx=10, pady=4)
        ctk.CTkEntry(line, textvariable=self.var_path).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(line, text="Procurar", width=100, command=lambda: self.browse(self.var_path)).pack(side="right", padx=6)

        opt_frame = ctk.CTkFrame(acard)
        opt_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(opt_frame, text="Formato:").pack(side="left", padx=5)
        self.combo_codec = ctk.CTkComboBox(opt_frame, values=["mp3", "wav", "m4a"])
        self.combo_codec.pack(side="left", padx=5)
        ctk.CTkLabel(opt_frame, text="✅ Metadados e Capa inclusos", text_color="#77dd77").pack(side="right", padx=10)

        btns = ctk.CTkFrame(acard)
        btns.pack(fill="x", padx=10, pady=8)
        self.btn_start_a = ctk.CTkButton(btns, text="⬇️ BAIXAR ÁUDIO", fg_color="#3a6afc", height=40, font=("Arial", 13, "bold"),
                                       command=lambda: self.start_download('audio'))
        self.btn_start_a.pack(side="left", fill="x", expand=True)
        self.btn_stop_a = ctk.CTkButton(btns, text="CANCELAR", fg_color="#FF0000", height=40, state="disabled", command=self.stop_download)
        self.btn_stop_a.pack(side="left", padx=8)

        self.prog_a = ctk.CTkProgressBar(acard, height=10)
        self.prog_a.set(0)
        self.prog_a.pack(fill="x", padx=10)
        self.lbl_audio_status = ctk.CTkLabel(acard, text="Pronto", font=("Consolas", 12))
        self.lbl_audio_status.pack(fill="x", pady=5)

    def start_download(self, mode):
        url = self.entry_video.get() if mode == 'video' else self.entry_audio.get()
        path = self.var_path.get()
        if not url: return
        
        playlist_mode = False
        if "playlist" in url or "&list=" in url:
            ans = messagebox.askyesno(
                "Playlist Detectada", 
                "Este link contém uma Playlist.\n\nDeseja baixar a PLAYLIST INTEIRA?\n\n(Sim = Playlist Toda / Não = Apenas este vídeo)"
            )
            playlist_mode = ans
            if not ans and "watch?v=" not in url:
                messagebox.showwarning("Aviso", "Este link é de uma página de playlist. Baixando playlist...")
                playlist_mode = True

        btn_start = self.btn_start_v if mode == 'video' else self.btn_start_a
        btn_stop = self.btn_stop_v if mode == 'video' else self.btn_stop_a
        prog = self.prog_v if mode == 'video' else self.prog_a
        lbl = self.lbl_video_status if mode == 'video' else self.lbl_audio_status
        
        btn_start.configure(state="disabled")
        btn_stop.configure(state="normal")
        lbl.configure(text="Iniciando...")

        def run_thread():
            try:
                codec = self.combo_codec.get() if mode == 'audio' else None
                pcb = lambda v: self.after(0, lambda: prog.set(v))
                scb = lambda t: self.after(0, lambda: lbl.configure(text=t))
                
                fpath, thumb, title = self.downloader.run(url, path, mode, codec, pcb, scb, playlist_mode)
                
                if fpath and title != "CANCELADO":
                    if thumb: self.after(0, lambda: self.add_history(title, fpath, thumb))
                    self.after(0, lambda: notify("Concluído", f"Finalizado: {title}"))
                    scb("✅ Sucesso!")
                    if playlist_mode: messagebox.showinfo("Playlist", f"Playlist salva em:\n{fpath}")
                elif title == "CANCELADO":
                    scb("🛑 Cancelado.")
                else:
                    scb("❌ Erro.")

            except Exception as e:
                err = str(e)
                if "Sign in" in err: msg = "Conteúdo restrito (login/idade)."
                elif "unavailable" in err: msg = "Vídeo removido/privado."
                else: msg = f"Erro: {err[:100]}"
                logger.error(f"Erro: {e}")
                scb(msg)
                self.after(0, lambda: messagebox.showerror("Falha", msg))
            finally:
                self.after(0, lambda: [btn_start.configure(state="normal"), btn_stop.configure(state="disabled"), prog.set(0)])

        threading.Thread(target=run_thread, daemon=True).start()

    def stop_download(self):
        self.downloader.stop()

    def browse(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)
            self.cfg.set('download_path', d)

    def add_history(self, title, path, thumb_url):
        card = ctk.CTkFrame(self.scroll_hist)
        card.pack(fill="x", padx=2, pady=2)
        
        img_lbl = ctk.CTkLabel(card, text="", width=90, height=68, fg_color="#222")
        img_lbl.pack(side="left", padx=8, pady=5)
        
        self.img_loader.load_image(thumb_url, lambda img: self.winfo_exists() and img_lbl.configure(image=img))

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info, text=title[:60], anchor="w", font=("Arial", 12, "bold")).pack(fill="x", padx=5)
        
        btns = ctk.CTkFrame(info, fg_color="transparent")
        btns.pack(anchor="w", padx=5)
        
        if os.path.isdir(path):
            ctk.CTkButton(btns, text="Abrir Pasta Playlist", width=120, height=24, 
                         command=lambda: os.startfile(path)).pack(side="left", padx=2)
        else:
            ctk.CTkButton(btns, text="Abrir", width=80, height=24, command=lambda: os.startfile(path)).pack(side="left", padx=2)
            ctk.CTkButton(btns, text="Pasta", width=80, height=24, command=lambda: subprocess.Popen(f'explorer /select,"{path}"')).pack(side="left")

        self.history_items.append({"widget": card, "title": title.lower()})

    def filter_history(self, *args):
        term = self.search_var.get().lower()
        for item in self.history_items:
            if term in item['title']: item['widget'].pack(fill="x", padx=2, pady=2)
            else: item['widget'].pack_forget()

    def clear_history(self):
        if messagebox.askyesno("Limpar", "Apagar histórico?"):
            for item in self.history_items: item['widget'].destroy()
            self.history_items.clear()

if __name__ == "__main__":
    CarriolaApp().mainloop()