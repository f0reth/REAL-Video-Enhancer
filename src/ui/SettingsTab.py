import os

from PySide6.QtWidgets import QMainWindow, QFileDialog
from ..constants import PLATFORM, HOME_PATH
from ..Util import currentDirectory, checkForWritePermissions, open_folder, log, FileHandler
from .QTcustom import RegularQTPopup
from ..GenerateFFMpegCommand import EncodingSettings, build_encoder_command
from ..VideoInfo import VideoLoader
from ..Settings import Settings
from PySide6.QtCore import QSignalBlocker

class SettingsTab:
    def __init__(
        self,
        parent: QMainWindow,
        halfPrecisionSupport,
        total_pytorch_gpus,
        total_ncnn_gpus,
    ):
        self.parent = parent
        self.input_file = None
        self.ffmpegInfoWrapper = None
        self.color_space = None
        self.color_primaries = None
        self.color_transfer = None
        self.in_pix_fmt = ""
        self.hdr_mode = False
        self.input_hdr = False
        self.ffmpeg_settings_dict = {
            "encoder": self.parent.encoder,
            "audio_encoder": self.parent.audio_encoder,
            "audio_bitrate": self.parent.audio_bitrate,
            "video_pixel_format": self.parent.video_pixel_format,
            "video_quality": self.parent.video_quality,

        }
        self.settings = parent.settings
        self.parent.EncoderCommand.setReadOnly(True)
        log("Settings: " + str(self.settings.values))
        self.connectSettingText() # has to be in this order, otherwise settings wont stick because they get reset.
        self.connectWriteSettings()
        self.parent.select_output_folder_location_btn.clicked.connect(self.selectOutputFolder)
        

        # disable half option if its not supported
        if not halfPrecisionSupport:
            self.parent.precision.removeItem(1)

        # set max gpu id for combo boxs
        self.parent.pytorch_gpu_id.setMaximum(total_pytorch_gpus)
        self.parent.ncnn_gpu_id.setMaximum(total_ncnn_gpus)
        self.parent.openRVEFolderBtn.clicked.connect(lambda:open_folder(currentDirectory()))
        

        self.updateFFMpegCommand()

    def updateFFMpegCommand(self):
        """
        Updates the FFMpegCommand object with the current settings.
        """
        self.settings.update(**{key: value.currentText() for key, value in self.ffmpeg_settings_dict.items()})
        
        self.out_pixel_fmt = self.settings.values.video_pixel_format
        pxfmtDict = {
                "yuv420p": "yuv420p",
                "yuv422p": "yuv422p",
                "yuv444p": "yuv444p",
                "yuv420p (10 bit)": "yuv420p10le",
                "yuv422p (10 bit)": "yuv422p10le",
                "yuv444p (10 bit)": "yuv444p10le",
            }
        self.out_pixel_fmt = pxfmtDict[self.out_pixel_fmt]

        input_file = self.parent.inputFileText.text()
        if input_file and len(input_file) > 1: # caching is nice
            if self.input_file != input_file:
                self.input_file = input_file
                self.ffmpegInfoWrapper = VideoLoader(self.input_file)
                self.ffmpegInfoWrapper.loadVideo()
                self.ffmpegInfoWrapper.getData()
                self.input_hdr = self.ffmpegInfoWrapper.is_hdr
                self.color_space = self.ffmpegInfoWrapper.color_space
                self.color_primaries = self.ffmpegInfoWrapper.color_primaries
                self.color_transfer = self.ffmpegInfoWrapper.color_transfer
                self.in_pix_fmt = self.ffmpegInfoWrapper.pixel_format


        self.hdr_mode = self.input_hdr and self.settings.values.auto_hdr_mode
        if self.hdr_mode or ("10" in self.in_pix_fmt and self.settings.values.auto_hdr_mode):
            pxfmtDict = {
                        "yuv420p": "yuv420p10le",
                        "yuv422p": "yuv422p10le",
                        "yuv444p": "yuv444p10le",
                    }

            if self.out_pixel_fmt in pxfmtDict:
                self.out_pixel_fmt = pxfmtDict[self.out_pixel_fmt]


        codec = self.settings.values.encoder.replace(' (experimental)', '').replace(' (40 series and up)', '')
        codec = {"vp9": "libvpx-vp9", "av1": "libsvtav1", "prores": "prores_ks", "x264_nvenc": "h264_nvenc", "x265_nvenc": "hevc_nvenc"}.get(codec, codec)
        labels = ("Lossless", "Ultra", "Very_High", "High", "Medium", "Low")
        index = labels.index(self.settings.values.video_quality)
        quality = (0, 10, 15, 20, 30, 40)[index] if codec in ("libvpx-vp9", "libsvtav1") else (0, 10, 15, 18, 23, 28)[index]
        speed_index = ("placebo", "slow", "medium", "fast", "fastest").index(self.settings.values.video_encoder_speed)
        presets = ("placebo", "slow", "medium", "fast", "veryfast")
        if codec.endswith("_nvenc"):
            presets = ("p7", "p6", "p4", "p2", "p1")
        elif codec == "libsvtav1":
            presets = ("0", "4", "8", "12", "13")
        elif codec == "libvpx-vp9":
            presets = ("0", "1", "2", "4", "5")
        self.parent.currentEncoding = EncodingSettings(
            codec=codec, quality=None if codec in ("ffv1", "utvideo", "prores_ks") else quality,
            preset=presets[speed_index] if codec not in ("ffv1", "utvideo", "prores_ks") else None,
            profile=5-index if codec == "prores_ks" else None,
            pixel_format=self.out_pixel_fmt,
            audio_codec={"copy_audio": "copy", "opus": "libopus"}.get(self.settings.values.audio_encoder, self.settings.values.audio_encoder),
            audio_bitrate=self.settings.values.audio_bitrate,
            subtitle_codec=self.settings.values.subtitle_encoder.replace("copy_subtitle", "copy"),
            color_space=self.color_space if self.in_pix_fmt != "yuv420p" else None,
            color_primaries=self.color_primaries, color_transfer=self.color_transfer,
            lossless=index == 0, hdr=self.hdr_mode)
        command = build_encoder_command(self.parent.currentEncoding)
        self.parent.EncoderCommand.setText(" ".join(command))
        self.parent.updateVideoGUIText()
         

    def connectWriteSettings(self):
        
        self.parent.subtitle_encoder.currentIndexChanged.connect(
            lambda: self.settings.writeSetting(
                "subtitle_encoder", self.parent.subtitle_encoder.currentText()
            )
        )

        self.parent.precision.currentIndexChanged.connect(
            lambda: self.settings.writeSetting(
                "precision", self.parent.precision.currentText()
            )
        )
        self.parent.tensorrt_optimization_level.currentIndexChanged.connect(
            lambda: self.settings.writeSetting(
                "tensorrt_optimization_level",
                self.parent.tensorrt_optimization_level.currentText(),
            )
        )
        self.parent.preview_enabled.stateChanged.connect(
            lambda: self.settings.writeSetting(
                "preview_enabled",
                "True" if self.parent.preview_enabled.isChecked() else "False",
            )
        )
        self.parent.scene_change_detection_enabled.stateChanged.connect(
            lambda: self.settings.writeSetting(
                "scene_change_detection_enabled",
                "True"
                if self.parent.scene_change_detection_enabled.isChecked()
                else "False",
            )
        )
        self.parent.discord_rich_presence.stateChanged.connect(
            lambda: self.settings.writeSetting(
                "discord_rich_presence",
                "True" if self.parent.discord_rich_presence.isChecked() else "False",
            )
        )
        self.parent.scene_change_detection_method.currentIndexChanged.connect(
            lambda: self.settings.writeSetting(
                "scene_change_detection_method",
                self.parent.scene_change_detection_method.currentText(),
            )
        )
        self.parent.scene_change_detection_threshold.valueChanged.connect(
            lambda: self.settings.writeSetting(
                "scene_change_detection_threshold",
                str(self.parent.scene_change_detection_threshold.value()),
            )
        )
        self.parent.video_quality.currentIndexChanged.connect(
            lambda: self.settings.writeSetting(
                "video_quality",
                str(self.parent.video_quality.currentText()),
            )
        )
        self.parent.output_folder_location.textChanged.connect(
            lambda: self.writeOutputFolder()
        )
        self.parent.use_same_output_folder_as_input_file_enabled.stateChanged.connect(
            lambda: self.settings.writeSetting(
                "use_same_output_folder_as_input_file_enabled",
                "True" if self.parent.use_same_output_folder_as_input_file_enabled.isChecked() else "False",
            )
        )

        self.parent.resetSettingsBtn.clicked.connect(self.resetSettings)

        self.parent.uhd_mode.stateChanged.connect(
            lambda: self.settings.writeSetting(
                "uhd_mode",
                "True" if self.parent.uhd_mode.isChecked() else "False",
            )
        )
        self.parent.ncnn_gpu_id.textChanged.connect(
            lambda: self.settings.writeSetting(
                "ncnn_gpu_id", self.parent.ncnn_gpu_id.text()
            )
        )
        self.parent.pytorch_gpu_id.textChanged.connect(
            lambda: self.settings.writeSetting(
                "pytorch_gpu_id", self.parent.pytorch_gpu_id.text()
            )
        )
        self.parent.auto_border_cropping.stateChanged.connect(
            lambda: self.settings.writeSetting(
                "auto_border_cropping",
                "True" if self.parent.auto_border_cropping.isChecked() else "False",
            )
        )
        self.parent.video_container.currentIndexChanged.connect(
            lambda: self.settings.writeSetting(
                "video_container", self.parent.video_container.currentText()
            )
        )
        self.parent.video_pixel_format.currentIndexChanged.connect(
            lambda: self.settings.writeSetting(
                "video_pixel_format", self.parent.video_pixel_format.currentText()
            )
        )
        self.parent.pytorch_version.currentIndexChanged.connect(
            lambda: self.settings.writeSetting(
                "pytorch_version", self.parent.pytorch_version.currentText()
            )
        )
        self.parent.pytorch_backend.currentIndexChanged.connect(
            lambda: self.settings.writeSetting(
                "pytorch_backend", self.parent.pytorch_backend.currentText()
            )
        )
        
        self.parent.dynamic_tensorrt_engine.stateChanged.connect(
            lambda: self.settings.writeSetting(
                "dynamic_tensorrt_engine",
                "True" if self.parent.dynamic_tensorrt_engine.isChecked() else "False"
            )
        )
        self.parent.auto_hdr_mode.stateChanged.connect(
            lambda: self.settings.writeSetting(
                "auto_hdr_mode",
                "True" if self.parent.auto_hdr_mode.isChecked() else "False"
            )
        )
        self.parent.video_encoder_speed.currentIndexChanged.connect(
            lambda: self.settings.writeSetting(
                "video_encoder_speed", self.parent.video_encoder_speed.currentText()
            )
        )
        self.parent.inputFileText.textChanged.connect(
            self.updateFFMpegCommand
        )
        self.parent.encoder.currentIndexChanged.connect(
            self.updateFFMpegCommand
        )
        self.parent.audio_encoder.currentIndexChanged.connect(
            self.updateFFMpegCommand
        )
        self.parent.video_pixel_format.currentIndexChanged.connect(
            self.updateFFMpegCommand
        )
        self.parent.audio_bitrate.currentIndexChanged.connect(
            self.updateFFMpegCommand
        )
        self.parent.auto_hdr_mode.stateChanged.connect(
            self.updateFFMpegCommand
        )
        self.parent.video_quality.currentIndexChanged.connect(
            self.updateFFMpegCommand
        )
        self.parent.video_encoder_speed.currentIndexChanged.connect(
            self.updateFFMpegCommand
        )
        self.parent.subtitle_encoder.currentIndexChanged.connect(
            self.updateFFMpegCommand
        )

    def writeOutputFolder(self):
        outputlocation = self.parent.output_folder_location.text()
        if not (os.path.exists(outputlocation) and os.path.isdir(outputlocation)):
            RegularQTPopup(
                "No videos folder\nSetting default output folder to home directory."
            )
            outputlocation = HOME_PATH
        if not checkForWritePermissions(outputlocation):
            RegularQTPopup(
                "No permissions to export here!\nSetting default output folder to home directory."
            )
            outputlocation = HOME_PATH

        self.settings.writeSetting(
            "output_folder_location",
            str(outputlocation),
        )

    def resetSettings(self):
        self.settings.writeDefaultSettings()
        from PySide6.QtCore import QObject
        blockers = [QSignalBlocker(widget) for widget in self.parent.findChildren(QObject)]
        self.connectSettingText()
        del blockers
        self.updateFFMpegCommand()

    def connectSettingText(self):
        if PLATFORM == "darwin":
            index = self.parent.encoder.findText("av1")
            self.parent.encoder.removeItem(index)

        self.parent.precision.setCurrentText(self.settings.values.precision)
        self.parent.tensorrt_optimization_level.setCurrentText(
            str(self.settings.values.tensorrt_optimization_level)
        )
        self.parent.encoder.setCurrentText(self.settings.values.encoder)
        self.parent.audio_encoder.setCurrentText(
            self.settings.values.audio_encoder
        )
        self.parent.audio_bitrate.setCurrentText(
            self.settings.values.audio_bitrate
        )
        self.parent.preview_enabled.setChecked(
            self.settings.values.preview_enabled
        )
        self.parent.discord_rich_presence.setChecked(
            self.settings.values.discord_rich_presence
        )
        self.parent.scene_change_detection_enabled.setChecked(
            self.settings.values.scene_change_detection_enabled
        )
        self.parent.scene_change_detection_method.setCurrentText(
            self.settings.values.scene_change_detection_method
        )
        self.parent.scene_change_detection_threshold.setValue(
            float(self.settings.values.scene_change_detection_threshold)
        )
        self.parent.video_quality.setCurrentText(
            self.settings.values.video_quality
        )
        self.parent.output_folder_location.setText(
            self.settings.values.output_folder_location
        )
        self.parent.use_same_output_folder_as_input_file_enabled.setChecked(
            self.settings.values.use_same_output_folder_as_input_file_enabled
        )
        self.parent.uhd_mode.setChecked(self.settings.values.uhd_mode)
        self.parent.ncnn_gpu_id.setValue(int(self.settings.values.ncnn_gpu_id))
        self.parent.pytorch_gpu_id.setValue(
            int(self.settings.values.pytorch_gpu_id)
        )
        self.parent.auto_border_cropping.setChecked(
            self.settings.values.auto_border_cropping
        )
        self.parent.video_container.setCurrentText(
            self.settings.values.video_container
        )
        self.parent.video_pixel_format.setCurrentText(
            self.settings.values.video_pixel_format
        )
        self.parent.pytorch_version.setCurrentText(
            self.settings.values.pytorch_version
        )
        self.parent.pytorch_backend.setCurrentText(
            self.settings.values.pytorch_backend
        )
        self.parent.dynamic_tensorrt_engine.setChecked(
            self.settings.values.dynamic_tensorrt_engine
        )
        self.parent.auto_hdr_mode.setChecked(
            self.settings.values.auto_hdr_mode
        )
        self.parent.video_encoder_speed.setCurrentText(
            self.settings.values.video_encoder_speed
        )
        self.parent.subtitle_encoder.setCurrentText(
            self.settings.values.subtitle_encoder
        )

    def selectOutputFolder(self):
        outputFile = QFileDialog.getExistingDirectory(
            parent=self.parent,
            caption="Select Folder",
            dir=os.path.expanduser("~"),
        )
        outputlocation = outputFile
        if os.path.exists(outputlocation) and os.path.isdir(outputlocation):
            if checkForWritePermissions(outputlocation):
                self.settings.writeSetting(
                    "output_folder_location",
                    str(outputlocation),
                )
                self.parent.output_folder_location.setText(outputlocation)
            else:
                RegularQTPopup("No permissions to export here!")
