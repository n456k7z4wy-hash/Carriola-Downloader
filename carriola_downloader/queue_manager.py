"""One network job at a time, independent cancellation, immutable UI snapshots."""

import logging
from queue import Queue
from threading import Event, RLock, Thread

from .engine import Cancelled, friendly_error
from .models import ACTIVE, RETRYABLE, Job
from .storage import Store

logger = logging.getLogger("Carriola")


class DownloadQueue:
    def __init__(self, store: Store, engine):
        self.store = store
        self.engine = engine
        self.events = Queue()
        self._pending = Queue()
        self._lock = RLock()
        self._closing = False
        self.jobs = {job.id: job for job in store.recover()}
        self._cancel = {}
        self._thread = Thread(target=self._work, name="CarriolaDownloads", daemon=True)
        self._thread.start()

    def _publish(self, job, *, persist=True):
        if persist:
            self.store.save(job)
        self.events.put(("job", job.snapshot()))

    def snapshots(self):
        with self._lock:
            return [job.snapshot() for job in self.jobs.values()]

    def submit(self, job: Job):
        job.validate()
        with self._lock:
            if self._closing:
                raise ValueError("O aplicativo está encerrando.")
            if any(
                other.state in ACTIVE and other.signature() == job.signature()
                for other in self.jobs.values()
            ):
                raise ValueError("Este download já está na fila.")
            self.store.save(job)
            self.jobs[job.id] = job
            self._cancel[job.id] = Event()
            self._publish(job, persist=False)
            self._pending.put(job.id)
        return job.id

    def cancel(self, job_id):
        with self._lock:
            job = self.jobs[job_id]
            if job.state not in ACTIVE:
                return
            self._cancel[job_id].set()
            if job.state == "queued":
                job.state, job.message = "cancelled", "Cancelado antes de iniciar."
            else:
                job.state, job.message = "cancelling", "Cancelando após a etapa atual…"
            self._publish(job)

    def retry(self, job_id):
        with self._lock:
            job = self.jobs[job_id]
            if job.state not in RETRYABLE or self._closing:
                return
            previous = job.snapshot()
            replacement = Job(**previous)
            replacement.state = "queued"
            replacement.progress = 0
            replacement.error = ""
            replacement.message = "Na fila para tentar novamente"
            # Reuse the same profile/path: yt-dlp resumes .part files when supported.
            self.submit(replacement)

    def clear_finished(self):
        with self._lock:
            ids = [key for key, job in self.jobs.items() if job.state not in ACTIVE]
            self.store.remove(ids)
            for key in ids:
                del self.jobs[key]
                self._cancel.pop(key, None)
            return ids

    def close(self):
        with self._lock:
            if self._closing:
                return
            self._closing = True
            for key in list(self.jobs):
                self.cancel(key)
            self._pending.put(None)

    def is_alive(self):
        return self._thread.is_alive()

    def _work(self):
        while True:
            job_id = self._pending.get()
            try:
                if job_id is None:
                    return
                with self._lock:
                    job = self.jobs.get(job_id)
                    if not job or job.state != "queued":
                        continue
                    cancel = self._cancel[job_id]
                    if cancel.is_set():
                        continue
                    job.state, job.message = "running", "Analisando link…"
                    self._publish(job)

                def emit(kind, data, job=job, cancel=cancel):
                    with self._lock:
                        if kind == "file":
                            job.files = [item for item in job.files if item["path"] != data["path"]]
                            job.files.append(data)
                            job.title = data["title"]
                            self._publish(job)
                        elif not cancel.is_set():
                            for key, value in data.items():
                                setattr(job, key, value)
                            self._publish(job, persist=False)

                try:
                    errors = self.engine.run(job, cancel, emit)
                    with self._lock:
                        if cancel.is_set():
                            raise Cancelled()
                        job.state = "partial" if errors else "completed"
                        job.progress = 1
                        job.error = "\n".join(errors)
                        job.message = f"{len(job.files)} arquivo(s) salvo(s)" + (
                            " · Alguns itens falharam." if errors else " · Concluído"
                        )
                except Exception as exc:
                    with self._lock:
                        if cancel.is_set() or isinstance(exc, Cancelled):
                            job.state, job.message = (
                                "cancelled",
                                "Cancelado. Arquivos já concluídos foram mantidos.",
                            )
                        else:
                            logger.exception("Download %s falhou", job.id)
                            job.state = "partial" if job.files else "failed"
                            job.error = str(exc)
                            job.message = friendly_error(str(exc))
                with self._lock:
                    self._publish(job)
            except Exception:
                # Keep the worker alive if history storage becomes unavailable.
                logger.exception("Falha ao atualizar a fila")
                with self._lock:
                    failed_job = self.jobs.get(job_id)
                    if failed_job:
                        failed_job.state = "failed"
                        failed_job.message = (
                            "Falha ao salvar o histórico. Confira espaço e permissões."
                        )
                        self._publish(failed_job, persist=False)
                self.events.put(
                    (
                        "error",
                        "Falha ao salvar o histórico. Confira espaço e permissões da pasta de dados.",
                    )
                )
            finally:
                self._pending.task_done()
