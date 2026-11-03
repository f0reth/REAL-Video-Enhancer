"""Exercise the retained Designer screen against the new foundation."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMainWindow
from src.Settings import Settings

APP = QApplication.instance() or QApplication([])


class WiringTests(unittest.TestCase):
    def test_settings_reset_queue_and_process_wiring(self):
        root = Path(__file__).resolve().parents[1]
        uic = Path(sys.executable).parent / ("pyside6-uic.exe" if os.name == "nt" else "pyside6-uic")
        code = subprocess.check_output([str(uic), str(root / "testRVEInterface.ui")], text=True, encoding="utf-8")
        code = "\n".join(line for line in code.splitlines() if not (line.startswith("import ") and line.endswith("_rc")))
        namespace = {}
        exec(code, namespace)
        with tempfile.TemporaryDirectory() as directory, patch("requests.head"):
            from src.ui.SettingsTab import SettingsTab
            from src.ui.ProcessTab import ProcessTab
            from src.ui.RenderQueue import RenderQueue
            for name in ("src.ui.SettingsTab.log", "src.ui.ProcessTab.log"):
                logging_patch = patch(name)
                logging_patch.start()
                self.addCleanup(logging_patch.stop)
            class Window(QMainWindow, namespace["Ui_MainWindow"]):
                pass
            window = Window()
            window.setupUi(window)
            window.settings = Settings(Path(directory) / "settings.json", directory)
            for name in ("updateVideoGUIText", "updateVideoGUIDetails", "addToRenderQueue", "openInputFile", "openBatchFiles", "loadVideo", "openOutputFolder", "startRender", "disableProcessPage", "enableProcessPage"):
                setattr(window, name, Mock())
            window.renderQueue = RenderQueue(window.renderQueueListWidget)
            settings_tab = SettingsTab(window, True, 0, 0)
            window.backendComboBox.clear()
            window.backendComboBox.addItem("pytorch (cpu)")
            process_tab = ProcessTab(window, window.settings)
            settings_tab.settings.writeSetting("precision", "float32")
            with patch("src.Settings.write_json", wraps=__import__("src.Settings", fromlist=["write_json"]).write_json) as write:
                settings_tab.resetSettings()
                self.assertEqual(write.call_count, 1)
            self.assertEqual(window.settings.values.precision, "auto")
            self.assertTrue(window.EncoderCommand.isReadOnly())
            window.video_quality.setCurrentText("Low")
            self.assertEqual(window.currentEncoding.quality, 28)
            process_tab.guiChangesOnRenderCompletion()
            process_tab.previewTimer.stop()
            window.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
