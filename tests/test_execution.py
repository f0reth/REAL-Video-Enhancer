from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from multiprocessing import shared_memory

import psutil
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from src.Command import RuntimePaths
from src.Execution import Executor
from src.Jobs import Job, JobState, ExecutionSettings
from src.Output import Reservations
from src.ModelSpec import ModelFile, ModelSpec
from unittest.mock import patch
from test_foundation import options


APP = QApplication.instance() or QApplication([])


def until(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while not predicate():
        APP.processEvents()
        time.sleep(.005)
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for executor")


class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = shutil.which("ffmpeg")
        if not cls.ffmpeg:
            raise unittest.SkipTest("ffmpeg required")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copyfile(Path(__file__).with_name("fake_backend.py"), self.root / "rve-backend.py")
        # Fixture imports production backend from an absolute path after being copied.
        script = self.root / "rve-backend.py"
        script.write_text(script.read_text().replace('str(Path(__file__).resolve().parents[1] / "backend")', repr(str(Path(__file__).resolve().parents[1] / "backend"))))
        self.video = self.root / "ok.mkv"
        subprocess.run([self.ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x48:r=10:d=4",
                        "-c:v", "ffv1", str(self.video)], check=True, capture_output=True)
        self.reservations = Reservations()
        self.paths = RuntimePaths(sys.executable, str(self.root), "", "", str(self.root), self.ffmpeg)
        self.executor = Executor(self.paths, self.reservations)
        self.jobs = []

    def job(self, mode="ok", **changes):
        source = self.root / (mode + ".mkv")
        if not source.exists():
            shutil.copyfile(self.video, source)
        job = Job(options(source, self.root / f"output-{len(self.jobs)}.mkv", **changes))
        job.output = self.reservations.reserve(job.id, job.options.inputFile, job.options.outputPath)
        self.jobs.append(job)
        return job

    def test_split_notifications_validate_and_commit(self):
        job = self.job()
        self.executor.submit([job])
        until(lambda: job.state == JobState.COMPLETED)
        self.assertTrue(Path(job.options.outputPath).exists())
        self.assertIsNone(self.executor.pause_memory)
        self.assertIsNone(self.executor.preview_memory)

    def test_crash_and_missing_completion_then_next_job(self):
        for mode in ("crash", "silent"):
            failed, good = self.job(mode), self.job()
            self.executor.submit([failed, good])
            until(lambda: good.state == JobState.COMPLETED)
            self.assertEqual(failed.state, JobState.FAILED)
            self.assertFalse(Path(failed.options.outputPath).exists())

    def test_failed_to_start(self):
        self.executor.paths = replace(self.paths, python=str(self.root / "missing.exe"))
        job = self.job()
        self.executor.submit([job])
        until(lambda: job.state == JobState.FAILED)
        self.assertIsNone(self.executor.pause_memory)
        self.assertFalse(Path(job.options.outputPath).exists())

    def test_reconfirmation_after_render_and_commit_retry(self):
        job = self.job()
        target = Path(job.options.outputPath)
        target.write_bytes(b"original")
        confirmations = []
        def confirm(current):
            confirmations.append(current.pending_identity)
            if len(confirmations) == 1:
                self.executor.approve(current, current.pending_identity)
        self.executor.confirmation.connect(confirm)
        changed = False
        def mutate(current):
            nonlocal changed
            if current.state == JobState.RUNNING and not changed:
                target.write_bytes(b"changed after consent")
                changed = True
        self.executor.changed.connect(mutate)
        self.executor.submit([job])
        until(lambda: len(confirmations) == 2)
        self.assertEqual(target.read_bytes(), b"changed after consent")
        self.assertTrue(job.output.temporary.exists())
        real_commit = job.output.commit
        with patch.object(job.output, "commit", side_effect=PermissionError("target locked")):
            self.executor.approve(job, job.pending_identity)
            until(lambda: job.state == JobState.FINALIZE_FAILED)
        self.assertTrue(job.output.temporary.exists())
        self.executor.retry_commit()
        until(lambda: job.state == JobState.COMPLETED)
        self.assertEqual(target.read_bytes(), self.video.read_bytes())

    def test_cleanup_failure_is_not_success(self):
        job = self.job("crash")
        with patch.object(job.output, "cleanup", side_effect=PermissionError("locked temporary")):
            self.executor.submit([job])
            until(lambda: job.state == JobState.FAILED)
        self.assertIn("cleanup failed", job.error)
        job.output.cleanup()

    def test_local_model_changed_before_start(self):
        weights = self.root / "weights.bin"
        weights.write_bytes(b"registered weights")
        model = ModelSpec("local", "Test model", "upscale", str(weights), 1,
                          ("ncnn",), files=(ModelFile.inspect(weights),))
        job = self.job(models=(model,))
        weights.write_bytes(b"changed weights")
        self.executor.submit([job])
        until(lambda: job.state == JobState.FAILED)
        self.assertIn("Model changed", job.error)
        self.assertFalse(Path(job.options.outputPath).exists())

    def test_pause_cancel_child_cleanup_and_next_job(self):
        job, good = self.job("pause"), self.job()
        self.executor.submit([job, good])
        until(lambda: "child_pid" in job.effective)
        memory_name = self.executor.pause_memory.name
        child_pid = job.effective["child_pid"]
        self.executor.pause()
        until(lambda: job.state == JobState.PAUSED)
        self.executor.resume()
        self.executor.cancel()
        until(lambda: good.state == JobState.COMPLETED)
        self.assertEqual(job.state, JobState.CANCELLED)
        until(lambda: not psutil.pid_exists(child_pid))
        with self.assertRaises(FileNotFoundError):
            shared_memory.SharedMemory(name=memory_name)


if __name__ == "__main__":
    unittest.main()
