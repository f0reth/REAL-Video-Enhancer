"""One serial executor for normal jobs and previews, driven by Qt signals."""
import os
import signal
import threading
from multiprocessing import shared_memory

from PySide6.QtCore import QObject, QProcess, QTimer, QThread, Signal

from .Command import build_command
from .Jobs import JobState
from .Output import ConfirmationRequired, FileIdentity
from .Preparation import Preparation
from .Protocol import Notifications


class OutputTask(QThread):
    """Large file fingerprints and filesystem publication must not block Qt."""
    def __init__(self, output, operation, parent):
        super().__init__(parent)
        self.output, self.operation = output, operation
        self.error = None
        self.identity = None
        self.cancelled = threading.Event()

    def run(self):
        try:
            if self.operation == "identity":
                self.identity = FileIdentity.read(self.output.target)
            else:
                self.output.commit(self.cancelled)
        except Exception as error:
            self.error = error


class Executor(QObject):
    changed = Signal(object)
    finished = Signal(object)
    confirmation = Signal(object)
    idle = Signal()

    def __init__(self, paths, reservations, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.reservations = reservations
        self.pending = []
        self.current = None
        self.process = None
        self.preparation = None
        self.output_task = None
        self.pause_memory = None
        self.preview_memory = None
        self.completed = False
        self.validated = False
        self.mode = ""
        self.pid = 0

    def submit(self, jobs):
        for job in jobs:
            if job is not self.current and job not in self.pending and job.state == JobState.WAITING:
                self.pending.append(job)
        if self.current is None:
            self._next()

    def _state(self, state):
        self.current.state = state
        self.changed.emit(self.current)

    def _next(self):
        if self.current is not None:
            return
        if not self.pending:
            self.idle.emit()
            return
        self.current = self.pending.pop(0)
        self.completed = self.validated = False
        try:
            self.current.options.validate()
        except Exception as error:
            self._finish(JobState.FAILED, str(error))
            return
        self._prepare()

    def approve(self, job, identity):
        if job is not self.current or job.state != JobState.AWAITING_REPLACEMENT:
            return
        job.output.approve(identity)
        if self.validated:
            self._commit()
        else:
            self._prepare()

    def _prepare(self):
        self._state(JobState.PREPARING)
        self.preparation_error = ""
        self.preparation = Preparation(self.current.options.models, self.current.output, self)
        self.preparation.stage.connect(self._preparation_stage)
        self.preparation.result.connect(self._prepared_result)
        self.preparation.finished.connect(self._prepared)
        self.preparation.start()

    def _preparation_stage(self, stage):
        self.current.progress = {"stage": stage}
        self.changed.emit(self.current)

    def _prepared_result(self, error):
        self.preparation_error = error

    def _prepared(self):
        self.preparation.deleteLater()
        self.preparation = None
        if self.current.state == JobState.CANCELLING:
            self._finish(JobState.CANCELLED)
            return
        if self.preparation_error:
            if isinstance(self.preparation_error, ConfirmationRequired):
                self._confirm()
            else:
                self._finish(JobState.FAILED, str(self.preparation_error))
            return
        try:
            job = self.current
            output = str(job.output.temporary)
            self.pause_memory = shared_memory.SharedMemory(create=True, size=1)
            self.pause_memory.buf[0] = 0
            options = job.options
            if options.execution.preview_enabled:
                channels = 6 if options.processing.hdr else 3
                self.preview_memory = shared_memory.SharedMemory(create=True,
                    size=options.video.width * options.video.height * options.processing.upscale_factor ** 2 * channels)
            command = build_command(options, self.paths, output, self.pause_memory.name,
                                    self.preview_memory.name if self.preview_memory else None)
            self._launch(command, "render")
        except ConfirmationRequired:
            self._confirm()
        except Exception as error:
            self._finish(JobState.FAILED, str(error))

    def _launch(self, command, mode):
        self.mode = mode
        self.parser = Notifications()
        self.validation_data = bytearray()
        process = QProcess(self)
        self.process = process
        self.pid = 0
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._stdout)
        process.readyReadStandardError.connect(self._stderr)
        process.started.connect(lambda: setattr(self, "pid", int(process.processId())))
        process.errorOccurred.connect(self._process_error)
        process.finished.connect(self._exited)
        process.setProgram(command[0])
        process.setArguments(command[1:])
        process.start()

    def _stdout(self, final=False):
        data = bytes(self.process.readAllStandardOutput())
        if self.mode != "render":
            self.validation_data.extend(data)
            return
        try:
            for event in self.parser.feed(data, final=final):
                kind = event["event"]
                if kind == "completed":
                    self.completed = True
                elif kind == "error":
                    self.current.error = event.get("message", "Backend failed")
                elif kind == "effective":
                    self.current.effective.update(event)
                elif kind == "stage":
                    self.current.progress = event
                    if event.get("stage") == "rendering" and self.current.state != JobState.CANCELLING:
                        self._state(JobState.RUNNING)
                elif kind == "progress":
                    self.current.progress = event
                elif kind == "paused" and self.current.state == JobState.PAUSING:
                    self._state(JobState.PAUSED)
                elif kind == "resumed" and self.current.state != JobState.CANCELLING:
                    self._state(JobState.RUNNING)
                self.changed.emit(self.current)
        except Exception as error:
            self.current.error = f"Notification protocol: {error}"
            self._kill()

    def _stderr(self):
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        if data:
            self.current.logs.append(data)
            self.changed.emit(self.current)

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            message = self.process.errorString()
            self.process.deleteLater()
            self.process = None
            self._finish(JobState.FAILED, message)

    def _exited(self, code, status):
        self._stdout(final=True)
        self._stderr()
        self._kill_group()
        self.process.deleteLater()
        self.process = None
        if self.mode == "render":
            self._release_memory()
        if self.current.state == JobState.CANCELLING:
            self._finish(JobState.CANCELLED)
        elif code != 0 or status != QProcess.ExitStatus.NormalExit or self.current.error:
            self._finish(JobState.FAILED, self.current.error or f"{self.mode} exited with code {code}")
        elif self.mode == "render":
            if not self.completed:
                self._finish(JobState.FAILED, "Backend exited without completion notification")
            elif self.current.options.processing.benchmark:
                self._finish(JobState.COMPLETED)
            else:
                self._state(JobState.FINALIZING)
                self._launch([self.paths.ffmpeg, "-nostdin", "-v", "error", "-xerror", "-progress", "pipe:1", "-nostats", "-i",
                              str(self.current.output.temporary), "-map", "0:v:0", "-f", "null", "-"], "validate")
        else:
            values = dict(line.split("=", 1) for line in self.validation_data.decode("utf-8", errors="replace").splitlines() if "=" in line)
            if int(values.get("frame", 0)) <= 0:
                self._finish(JobState.FAILED, "Output contains no decoded video frames")
                return
            self.validated = True
            self._commit()

    def _commit(self):
        self._state(JobState.FINALIZING)
        self.output_task = OutputTask(self.current.output, "commit", self)
        self.output_task.finished.connect(self._committed)
        self.output_task.start()

    def _committed(self):
        task = self.output_task
        self.output_task = None
        task.deleteLater()
        if isinstance(task.error, ConfirmationRequired):
            if self.current.state == JobState.CANCELLING:
                self._finish(JobState.CANCELLED)
            else:
                self._confirm()
        elif isinstance(task.error, InterruptedError):
            self._finish(JobState.CANCELLED)
        elif task.error:
            self.current.error = f"{task.error}; temporary output: {self.current.output.temporary}; backup: {self.current.output.backup}"
            self._release_memory()
            # Preserve the validated artifact for explicit retry/cancel.
            self._state(JobState.FINALIZE_FAILED)
        else:
            # Publication already committed: a late cancel must not label it cancelled.
            self._finish(JobState.COMPLETED)

    def _confirm(self):
        self.output_task = OutputTask(self.current.output, "identity", self)
        self.output_task.finished.connect(self._identity_read)
        self.output_task.start()

    def _identity_read(self):
        task = self.output_task
        self.output_task = None
        task.deleteLater()
        if self.current.state == JobState.CANCELLING:
            self._finish(JobState.CANCELLED)
        elif task.error:
            self._finish(JobState.FAILED, str(task.error))
        else:
            self.current.pending_identity = task.identity
            self._state(JobState.AWAITING_REPLACEMENT)
            self.confirmation.emit(self.current)

    def retry_commit(self):
        if self.current and self.current.state == JobState.FINALIZE_FAILED:
            self.current.error = ""
            self._commit()

    def pause(self):
        if self.current and self.current.state == JobState.RUNNING:
            self.pause_memory.buf[0] = 1
            self._state(JobState.PAUSING)

    def resume(self):
        if self.current and self.current.state in (JobState.PAUSING, JobState.PAUSED):
            self.pause_memory.buf[0] = 0
            self._state(JobState.RUNNING)

    def cancel(self, job=None):
        job = job or self.current
        if job in self.pending:
            self.pending.remove(job)
            job.state = JobState.CANCELLED
            self.reservations.release(job.id)
            self.finished.emit(job)
            return
        if not job or job is not self.current:
            return
        if job.output.published:
            self.retry_commit()
            return
        self._state(JobState.CANCELLING)
        if self.preparation:
            self.preparation.cancelled.set()
        elif self.output_task:
            self.output_task.cancelled.set()
        elif self.process:
            process = self.process
            process.write(b"cancel\n")
            QTimer.singleShot(2000, lambda: self._kill() if self.process is process else None)
        else:
            self._finish(JobState.CANCELLED)

    def _kill_group(self):
        if os.name != "nt" and self.pid:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _kill(self):
        self._kill_group()
        if self.process:
            self.process.kill()

    def _release_memory(self):
        for attribute in ("pause_memory", "preview_memory"):
            memory = getattr(self, attribute)
            if memory:
                memory.close()
                try:
                    memory.unlink()
                except FileNotFoundError:
                    pass
                setattr(self, attribute, None)

    def _finish(self, state, error=""):
        job = self.current
        job.error = error or job.error
        if job.output.backup:
            job.error += f"; original output preserved at: {job.output.backup}"
        try:
            job.output.cleanup()
        except OSError as failure:
            job.error += f"; cleanup failed: {failure}; temporary: {job.output.temporary}"
            state = JobState.FAILED
        self._release_memory()
        job.state = state
        self.reservations.release(job.id)
        self.current = None
        self.finished.emit(job)
        QTimer.singleShot(0, self._next)
