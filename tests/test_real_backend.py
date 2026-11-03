"""CPU integration: generated small Compact model and generated video, no downloads."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class RealBackendTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("torch"), "CPU torch required")
    def test_model_probe_and_trimmed_render(self):
        root = Path(__file__).resolve().parents[1]
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            self.skipTest("FFmpeg and FFprobe required")
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model, source, target = (directory / name for name in ("compact.pth", "input.mkv", "output.mkv"))
            generate = """
import sys, torch
from src.pytorch.spandrel.architectures.Compact.__arch.SRVGG import SRVGGNetCompact
torch.manual_seed(1)
model = SRVGGNetCompact(num_feat=4, num_conv=1, upscale=2)
for parameter in model.parameters():
    parameter.data.zero_()
torch.save(model.state_dict(), sys.argv[1])
"""
            result = subprocess.run([sys.executable, "-c", generate, str(model)], cwd=root / "backend", capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x48:r=10:d=4",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "ffv1", "-c:a", "pcm_s16le", str(source)], check=True, capture_output=True)
            probe = subprocess.run([sys.executable, str(root / "backend/model-probe.py"), "pytorch", str(model)], capture_output=True, text=True, timeout=60)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(next(json.loads(line)["scale"] for line in probe.stdout.splitlines() if json.loads(line)["event"] == "model"), 2)
            from src.Command import RuntimePaths
            from src.Execution import Executor
            from src.GenerateFFMpegCommand import EncodingSettings
            from src.Jobs import Job, JobState, ExecutionSettings, ProcessingSettings
            from src.ModelSpec import local_model
            from src.Output import Reservations
            from test_foundation import options
            from test_execution import until
            snapshot = options(source, target, backend="pytorch (cpu)", startTime=1, endTime=2.5,
                processing=ProcessingSettings(upscale_factor=2),
                execution=ExecutionSettings(precision="float32"),
                encoding=EncodingSettings(codec="ffv1", quality=None, preset=None, audio_codec="pcm_s16le"),
                models=(local_model(model, "pytorch", 2),))
            job = Job(snapshot)
            reservations = Reservations()
            job.output = reservations.reserve(job.id, str(source), str(target))
            executor = Executor(RuntimePaths(sys.executable, str(root / "backend"), "", "", str(directory), ffmpeg), reservations)
            executor.submit([job])
            until(lambda: job.state in (JobState.COMPLETED, JobState.FAILED), seconds=60)
            self.assertEqual(job.state, JobState.COMPLETED, job.error + "\n" + "".join(job.logs))
            probe = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)], capture_output=True, text=True, check=True)
            info = json.loads(probe.stdout)
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"]), (128, 96))
            self.assertAlmostEqual(float(info["format"]["duration"]), 1.5, delta=.1)
            import numpy as np
            def first_rgb(path, seek=0, scale=False):
                command = [ffmpeg, "-v", "error", "-i", str(path), "-ss", str(seek), "-frames:v", "1"]
                if scale:
                    command += ["-vf", "scale=128:96:flags=neighbor"]
                return np.frombuffer(subprocess.check_output(command + ["-pix_fmt", "rgb24", "-f", "rawvideo", "-"]), dtype=np.uint8).astype(float)
            actual = first_rgb(target)
            expected = first_rgb(source, seek=1, scale=True)
            wrong_start = first_rgb(source, scale=True)
            self.assertLess(np.abs(actual - expected).mean(), 8)
            self.assertLess(np.abs(actual - expected).mean(), np.abs(actual - wrong_start).mean())


if __name__ == "__main__":
    unittest.main()
