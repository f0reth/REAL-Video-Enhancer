"""Cancellable preparation outside the GUI thread; no widget access."""
from pathlib import Path
import os
import tarfile
import tempfile
import threading
import urllib.request

from PySide6.QtCore import QThread, Signal


class Preparation(QThread):
    stage = Signal(str)
    result = Signal(object)

    def __init__(self, models, output, parent=None):
        super().__init__(parent)
        self.models = models
        self.output = output
        self.cancelled = threading.Event()

    def run(self):
        try:
            for model in self.models:
                if self.cancelled.is_set():
                    raise InterruptedError("Preparation cancelled")
                self.stage.emit(f"Validating {model.name}")
                model.verify()
                if model.download and not Path(model.path).exists():
                    self.download(model)
                if not Path(model.path).exists():
                    raise FileNotFoundError(model.path)
            if self.cancelled.is_set():
                raise InterruptedError("Preparation cancelled")
            self.output.create_temporary()
            self.result.emit(None)
        except Exception as error:
            self.result.emit(error)

    def download(self, model):
        target = Path(model.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".rve-download-", dir=target.parent) as directory:
            archive = Path(directory) / "download"
            url = "https://github.com/TNTwise/real-video-enhancer-models/releases/download/models/" + model.download
            with urllib.request.urlopen(url, timeout=10) as response, archive.open("wb") as stream:
                total = response.headers.get("Content-Length", "unknown")
                received = 0
                while chunk := response.read(1024 * 256):
                    if self.cancelled.is_set():
                        raise InterruptedError("Download cancelled")
                    stream.write(chunk)
                    received += len(chunk)
                    self.stage.emit(f"Downloading {model.name}: {received}/{total} bytes")
            if model.download.endswith(".tar.gz"):
                unpacked = Path(directory) / "unpacked"
                with tarfile.open(archive) as tar:
                    tar.extractall(unpacked, filter="data")
                source = unpacked / target.name
                if not source.exists():
                    raise ValueError(f"Model archive lacks {target.name}")
                # Do not overwrite existing weights, even if another app installs them.
                os.rename(source, target)
            else:
                os.link(archive, target)
