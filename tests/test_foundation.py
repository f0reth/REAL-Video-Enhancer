from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.Command import RuntimePaths, build_command
from src.Jobs import ExecutionSettings, RenderOptions, VideoInfo, ProcessingSettings
from src.ModelSpec import ModelFile, ModelRegistry, ModelSpec, local_model
from src.Output import ConfirmationRequired, FileIdentity, OutputReservation, Reservations, publish_no_replace
from src.Protocol import Notifications
from src.Settings import Settings


def options(source="input.mp4", target="output.mkv", **changes):
    processing = changes.pop("processing", ProcessingSettings())
    if "hdrMode" in changes:
        processing = replace(processing, hdr=changes.pop("hdrMode"))
    return replace(RenderOptions(str(source), str(target), VideoInfo(64, 48, 10, 40), processing, "ncnn"), **changes)



class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "input.mp4"
        self.source.write_bytes(b"input")
        self.target = self.root / "output.mkv"

    def test_atomic_typed_settings_and_snapshot(self):
        path = self.root / "settings.json"
        settings = Settings(path)
        before = settings.values
        settings.writeSetting("precision", "float32")
        self.assertEqual(before.precision, "auto")
        self.assertEqual(Settings(path).values.precision, "float32")
        data = json.loads(path.read_text())
        self.assertIs(type(data["preview_enabled"]), bool)
        with patch("src.atomic.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                settings.writeSetting("precision", "float16")
        self.assertEqual(Settings(path).values.precision, "float32")
        settings.writeDefaultSettings()
        self.assertEqual(Settings(path).values, settings.defaults)

    def test_command_is_pure_and_has_interval(self):
        snapshot = options(startTime=1, endTime=2, execution=ExecutionSettings(precision="float32"))
        paths = RuntimePaths("python", "backend", "models", "custom", ".", "ffmpeg")
        command = build_command(snapshot, paths, "temporary.mkv", "pause")
        self.assertEqual(command[command.index("--start_time") + 1], "1")
        self.assertEqual(command[command.index("--end_time") + 1], "2")
        self.assertEqual(snapshot.backend, "ncnn")
        self.assertEqual(command, build_command(snapshot, paths, "temporary.mkv", "pause"))
        with self.assertRaises(FrozenInstanceError):
            snapshot.backend = "pytorch"

    def test_incremental_unicode_and_truncated_protocol(self):
        payload = (json.dumps({"event": "stage", "stage": "準備"}, ensure_ascii=False) + "\n" +
                   '{"event":"completed"}\n').encode()
        parser = Notifications()
        result = []
        for byte in payload:
            result += parser.feed(bytes([byte]))
        self.assertEqual(len(result), 2)
        parser.feed(b'{"event":')
        with self.assertRaises(ValueError):
            parser.feed(b"", final=True)

    def test_input_hardlink_and_duplicate_reservations(self):
        os.link(self.source, self.target)
        with self.assertRaises(ValueError):
            OutputReservation(self.source, self.target)
        self.target.unlink()
        reservations = Reservations()
        reservations.reserve("a", self.source, self.target)
        with self.assertRaises(ValueError):
            reservations.reserve("b", self.source, self.root / "." / self.target.name)
        reservations.release("a")
        reservations.reserve("b", self.source, self.target)

    def test_changed_target_needs_new_consent(self):
        self.target.write_bytes(b"old")
        output = OutputReservation(self.source, self.target)
        with self.assertRaises(ConfirmationRequired):
            output.check()
        output.approve(FileIdentity.read(self.target))
        temporary = Path(output.create_temporary())
        temporary.write_bytes(b"new")
        self.target.write_bytes(b"changed")
        with self.assertRaises(ConfirmationRequired):
            output.commit()
        self.assertEqual(self.target.read_bytes(), b"changed")
        output.approve(FileIdentity.read(self.target))
        output.commit()
        self.assertEqual(self.target.read_bytes(), b"new")
        self.assertEqual(self.source.read_bytes(), b"input")

    def test_no_clobber_when_target_created_during_commit(self):
        output = OutputReservation(self.source, self.target)
        Path(output.create_temporary()).write_bytes(b"render")
        def race(source, target):
            self.target.write_bytes(b"someone else")
            publish_no_replace(source, target)
        with patch("src.Output.publish_no_replace", side_effect=race):
            with self.assertRaises(FileExistsError):
                output.commit()
        self.assertEqual(self.target.read_bytes(), b"someone else")
        output.cleanup()

    def test_publication_failure_restores_old_file(self):
        self.target.write_bytes(b"original")
        output = OutputReservation(self.source, self.target)
        output.approve(FileIdentity.read(self.target))
        Path(output.create_temporary()).write_bytes(b"new")
        def fail_new(source, target):
            if source == output.temporary:
                raise PermissionError("locked")
            return publish_no_replace(source, target)
        with patch("src.Output.publish_no_replace", side_effect=fail_new):
            with self.assertRaises(PermissionError):
                output.commit()
        self.assertEqual(self.target.read_bytes(), b"original")
        self.assertTrue(output.temporary.exists())
        output.cleanup()

    def test_local_model_set_hash_and_unregister(self):
        directory = self.root / "model"
        directory.mkdir()
        (directory / "model.param").write_text("parameters")
        with self.assertRaises(ValueError):
            local_model(directory, "ncnn", 2)
        weights = directory / "model.bin"
        weights.write_bytes(b"weights")
        model = local_model(directory, "ncnn", 2)
        registry = ModelRegistry(self.root / "models.json")
        registry.register(model)
        loaded = ModelRegistry(registry.path).models[model.id]
        self.assertEqual(model, loaded)
        registry.remove(model.id)
        self.assertTrue(weights.exists())
        weights.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            loaded.verify()

    def test_unsupported_options_rejected(self):
        with self.assertRaises(ValueError):
            options(hdrMode=True).validate()
        with self.assertRaises(ValueError):
            options(startTime=3, endTime=2).validate()


if __name__ == "__main__":
    unittest.main()
