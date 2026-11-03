import os
import subprocess
from dataclasses import asdict
from PySide6.QtCore import QProcess, QTimer, QThread, Signal, Qt
from PySide6.QtGui import QImage, QPixmap, QFontMetrics
from PySide6.QtWidgets import QMessageBox
from .AnimationHandler import AnimationHandler
from .QTcustom import RegularQTPopup, show_layout_widgets, hide_layout_widgets
from ..constants import BACKEND_PATH, PYTHON_EXECUTABLE_PATH, MODELS_PATH, CUSTOM_MODELS_PATH, FFMPEG_PATH, CWD, PLATFORM
from ..Util import log
from ..ModelHandler import getModels
from ..ModelSpec import local_model, ModelRegistry
from ..Jobs import JobState
from ..Command import RuntimePaths
from ..Execution import Executor
from ..Output import FileIdentity
from ..Protocol import Notifications


class RegisterModel(QThread):
    result = Signal(str)

    def __init__(self, path, backend, scale, files, parent):
        super().__init__(parent)
        self.path, self.backend, self.scale = path, backend, scale
        self.files = files

    def run(self):
        try:
            model = local_model(self.path, self.backend, self.scale)
            if [asdict(file) for file in model.files] != self.files:
                raise ValueError("Model changed since inspection; register it again")
            ModelRegistry(os.path.join(CWD, "models.json")).register(model)
            self.result.emit("")
        except Exception as error:
            self.result.emit(str(error))


class ProcessTab:
    def __init__(self, parent, settings):
        self.parent = parent
        self.settings = settings
        self.animationHandler = AnimationHandler()
        self.tileUpAnimationHandler = AnimationHandler()
        self.tileDownAnimationHandler = AnimationHandler()
        self.paths = RuntimePaths(PYTHON_EXECUTABLE_PATH, BACKEND_PATH, MODELS_PATH, CUSTOM_MODELS_PATH, CWD, FFMPEG_PATH)
        self.executor = Executor(self.paths, parent.renderQueue.reservations, parent)
        self.executor.changed.connect(self.updateJob)
        self.executor.finished.connect(self.jobFinished)
        self.executor.confirmation.connect(self.confirmReplacement)
        self.executor.idle.connect(self.guiChangesOnRenderCompletion)
        self.previewTimer = QTimer(parent)
        self.previewTimer.setInterval(200)
        self.previewTimer.timeout.connect(self.updatePreview)
        self.previewTimer.start()
        self.registration = None
        self.registration_worker = None
        self.QConnect()
        self.populateModels(parent.backendComboBox.currentText())

    def populateModels(self, backend) -> dict:
        """
        returns
        the current models available given a method (interpolate, upscale) and a backend (ncnn, tensorrt, pytorch)
        """
        interpolateModels, upscaleModels, deblurModels, denoiseModels, decompressModels, _ = getModels(backend)
        self.parent.interpolateModelComboBox.clear()
        self.parent.upscaleModelComboBox.clear()
        self.parent.deblurModelComboBox.clear()
        self.parent.denoiseModelComboBox.clear()
        self.parent.decompressModelComboBox.clear()
        self.parent.interpolateModelComboBox.addItems(
            list(interpolateModels.keys())
        )
        self.parent.interpolateModelComboBox.setCurrentIndex(len(list(interpolateModels.keys()))-1)
        self.parent.upscaleModelComboBox.addItems(list(upscaleModels.keys()))
        self.parent.deblurModelComboBox.addItems(list(deblurModels.keys()))
        self.parent.denoiseModelComboBox.addItems(list(denoiseModels.keys()))
        self.parent.decompressModelComboBox.addItems(list(decompressModels.keys()))
    def onTilingSwitch(self):
        if self.parent.tilingCheckBox.isChecked():
            self.parent.tileSizeContainer.setVisible(True)
            self.tileDownAnimationHandler.dropDownAnimation(
                self.parent.tileSizeContainer
            )
        else:
            self.tileUpAnimationHandler.moveUpAnimation(self.parent.tileSizeContainer)
            self.parent.tileSizeContainer.setVisible(False)

    def openOutputFolderInExplorer(self):
        output_folder = os.path.dirname(self.parent.outputFileText.text())
        if os.path.isdir(output_folder):
            if PLATFORM == "win32":
                os.startfile(output_folder)
            elif PLATFORM == "darwin":
                subprocess.Popen(["open", output_folder])
            else:
                subprocess.Popen(["xdg-open", output_folder])

    def QConnect(self):
        # connect file select buttons
        self.parent.addToRenderQueueButton.clicked.connect(self.parent.addToRenderQueue)
        self.parent.RemoveFromRenderQueue.clicked.connect(
            self.parent.renderQueue.remove
        )
        self.parent.MoveUpRenderQueue.clicked.connect(
            lambda: self.parent.renderQueue.moveitem("up")
        )
        self.parent.MoveDownRenderQueue.clicked.connect(
            lambda: self.parent.renderQueue.moveitem("down")
        )
        self.parent.inputFileSelectButton.clicked.connect(self.parent.openInputFile)
        self.parent.batchSelectButton.clicked.connect(self.parent.openBatchFiles)
        self.parent.inputFileText.textChanged.connect(self.parent.loadVideo)
        self.parent.outputFileSelectButton.clicked.connect(self.parent.openOutputFolder)
        self.parent.openOutputFolderButton.clicked.connect(self.openOutputFolderInExplorer)
        # connect render button
        self.parent.startRenderButton.clicked.connect(self.parent.startRender)
        # set tile size visible to false by default
        self.parent.tileSizeContainer.setVisible(False)
        # set slo mo container visable to false by default
        
        self.parent.interpolateContainer_2.setVisible(False)
        # connect up tilesize container visiable
        self.parent.tilingCheckBox.stateChanged.connect(self.onTilingSwitch)

        self.parent.interpolationMultiplierSpinBox.valueChanged.connect(
            self.parent.updateVideoGUIDetails
        )

        self.parent.upscaleModelComboBox.currentIndexChanged.connect(
            self.parent.updateVideoGUIDetails
        )
        self.parent.upscaleScaleSpinBox.valueChanged.connect(
            self.parent.updateVideoGUIDetails
        )
        self.parent.interpolateModelComboBox.currentIndexChanged.connect(
            self.parent.updateVideoGUIDetails
        )
        self.parent.decompressModelComboBox.currentIndexChanged.connect(
            self.parent.updateVideoGUIDetails
        )
        self.parent.interpolateCheckBox.clicked.connect(self.parent.updateVideoGUIDetails)
        self.parent.upscaleCheckBox.clicked.connect(self.parent.updateVideoGUIDetails)
        self.parent.deblurCheckBox.clicked.connect(self.parent.updateVideoGUIDetails)
        self.parent.denoiseCheckBox.clicked.connect(self.parent.updateVideoGUIDetails)
        self.parent.decompressCheckBox.clicked.connect(self.parent.updateVideoGUIDetails)   
        self.parent.sloMoModeCheckBox.clicked.connect(self.parent.updateVideoGUIDetails)  
        self.parent.backendComboBox.currentIndexChanged.connect(
            lambda: self.populateModels(self.parent.backendComboBox.currentText())
        )
        self.parent.EncoderCommand.textChanged.connect(lambda: self.parent.EncoderCommand.setFixedWidth(max(50, QFontMetrics(self.parent.EncoderCommand.font()).horizontalAdvance(self.parent.EncoderCommand.text()) + 10)))
        # connect up pausing
        hide_layout_widgets(self.parent.onRenderButtonsContiainer)
        self.parent.pauseRenderButton.clicked.connect(self.pauseRender)
        self.parent.killRenderButton.clicked.connect(self.killRenderProcess)

    def run(self, renderQueue):
        self.submit([job for job in renderQueue.queue if job.state == JobState.WAITING])

    def submit(self, jobs):
        if not jobs:
            self.guiChangesOnRenderCompletion()
            return
        self.parent.disableProcessPage()
        show_layout_widgets(self.parent.onRenderButtonsContiainer)
        self.parent.startRenderButton.setVisible(False)
        self.executor.submit(jobs)

    def confirmReplacement(self, job):
        try:
            identity = job.pending_identity
            answer = QMessageBox.question(self.parent, "Replace output?",
                f"Replace this output for this job?\n{job.output.target}\nThe existing file is kept until the new output is validated.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.executor.approve(job, identity)
            else:
                self.executor.cancel(job)
        except OSError as error:
            job.error = str(error)
            self.executor.cancel(job)

    def killRenderProcess(self):
        for job in self.executor.pending[:]:
            self.executor.cancel(job)
        self.executor.cancel()

    def shutdown(self, callback):
        self.killRenderProcess()
        if self.registration:
            process = self.registration
            process.write(b"cancel\n")
            QTimer.singleShot(2000, lambda: process.kill() if self.registration is process else None)
        def drained():
            if self.executor.current or self.executor.pending or self.registration or self.registration_worker:
                QTimer.singleShot(100, drained)
            else:
                callback()
        drained()

    def pauseRender(self):
        self.executor.pause()

    def resumeRender(self):
        self.executor.resume()

    def updateJob(self, job):
        event = job.progress
        self.parent.STATUS.setText(f"Status: {job.state.value} {event.get('stage', '')}")
        self.parent.FPS.setText(f"FPS: {event.get('fps', '')}")
        self.parent.ETA.setText(f"ETA: {event.get('eta', '')}")
        self.parent.progressBar.setRange(0, int(event.get('total', 0)))
        self.parent.progressBar.setValue(int(event.get('processed', 0)))
        self.parent.renderOutput.setPlainText("".join(job.logs[-200:]) + ("\n" + job.error if job.error else ""))
        self.parent.renderQueue.refresh()
        self.parent.pauseRenderButton.setEnabled(job.state == JobState.RUNNING)
        if job.state == JobState.PAUSED:
            self.parent.startRenderButton.setVisible(True)
            self.parent.startRenderButton.setEnabled(True)
            self.parent.startRenderButton.clicked.disconnect()
            self.parent.startRenderButton.clicked.connect(self.resumeRender)
        else:
            self.parent.startRenderButton.setVisible(False)
        if job.state == JobState.FINALIZE_FAILED:
            answer = QMessageBox.question(self.parent, "Output publication failed", job.error + "\nRetry publication?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                QTimer.singleShot(0, self.executor.retry_commit)
            else:
                # Keep the validated temporary output and reservation for a later retry.
                self.parent.startRenderButton.setVisible(True)
                self.parent.startRenderButton.setEnabled(True)
                self.parent.startRenderButton.clicked.disconnect()
                self.parent.startRenderButton.clicked.connect(self.executor.retry_commit)

    def updatePreview(self):
        memory = self.executor.preview_memory
        job = self.executor.current
        if not memory or not job:
            return
        options = job.options
        width = options.video.width * options.processing.upscale_factor
        height = options.video.height * options.processing.upscale_factor
        channels = 6 if options.processing.hdr else 3
        data = bytes(memory.buf[:width * height * channels])
        if channels == 6:
            import numpy as np
            data = (np.frombuffer(data, dtype=np.uint16) >> 8).astype(np.uint8).tobytes()
        image = QImage(data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
        self.parent.previewLabel.setPixmap(QPixmap.fromImage(image).scaled(
            self.parent.previewLabel.size(), Qt.AspectRatioMode.KeepAspectRatio))

    def jobFinished(self, job):
        self.parent.renderQueue.refresh()
        if job.state == JobState.COMPLETED and not job.options.processing.benchmark:
            self.parent.OutputFilesListWidget.addItem(job.options.outputPath)
        if job.error:
            log(job.error)
            self.parent.renderOutput.append(job.error)
        if job.state == JobState.COMPLETED and job.options.isPreview:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QMediaPlayer
            self.previewPlayer = QMediaPlayer(self.parent)
            self.previewPlayer.setSource(QUrl.fromLocalFile(job.options.outputPath))
            self.previewPlayer.setVideoOutput(self.parent.VideoPreview)
            self.parent.VideoPreview.show()
            self.parent.previewLabel.hide()
            self.parent.timeInVideoScrollBar.setRange(0, int((job.options.endTime - job.options.startTime) * 10))
            try:
                self.parent.timeInVideoScrollBar.valueChanged.disconnect()
            except RuntimeError:
                pass
            self.parent.timeInVideoScrollBar.valueChanged.connect(lambda value: self.previewPlayer.setPosition(value * 100))
            self.previewPlayer.play()
            self.previewPlayer.pause()

    def guiChangesOnRenderCompletion(self):
        hide_layout_widgets(self.parent.onRenderButtonsContiainer)
        self.parent.startRenderButton.clicked.disconnect()
        self.parent.startRenderButton.clicked.connect(self.parent.startRender)
        self.parent.startRenderButton.setVisible(True)
        self.parent.startRenderButton.setEnabled(True)
        self.parent.enableProcessPage()

    def registerModel(self, path, backend):
        if self.registration or self.registration_worker:
            RegularQTPopup("Model registration is already running")
            return
        process = QProcess(self.parent)
        self.registration = process
        parser = Notifications()
        records = []
        errors = []
        def read():
            try:
                records.extend(parser.feed(bytes(process.readAllStandardOutput())))
            except Exception as error:
                errors.append(str(error))
        process.readyReadStandardOutput.connect(read)
        process.readyReadStandardError.connect(lambda: errors.append(bytes(process.readAllStandardError()).decode("utf-8", errors="replace")))
        def finished(code, status):
            read()
            try:
                parser.feed(b"", final=True)
                if code or status != QProcess.ExitStatus.NormalExit:
                    raise ValueError("Model inspection failed: " + "".join(errors)[-3000:])
                result = next(record for record in records if record["event"] == "model")
                worker = RegisterModel(path, backend, result["scale"], result["files"], self.parent)
                self.registration_worker = worker
                worker.result.connect(lambda error: RegularQTPopup(error) if error else self.populateModels(self.parent.backendComboBox.currentText()))
                def registered():
                    self.registration_worker = None
                    worker.deleteLater()
                worker.finished.connect(registered)
                worker.start()
            except Exception as error:
                RegularQTPopup(str(error))
            self.registration = None
            process.deleteLater()
        process.finished.connect(finished)
        def start_error(error):
            if error == QProcess.ProcessError.FailedToStart:
                RegularQTPopup(process.errorString())
                self.registration = None
                process.deleteLater()
        process.errorOccurred.connect(start_error)
        process.start(PYTHON_EXECUTABLE_PATH, [os.path.join(BACKEND_PATH, "model-probe.py"), backend, path])
