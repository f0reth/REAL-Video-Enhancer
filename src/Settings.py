"""Typed application defaults, persisted only in the current JSON format."""
from dataclasses import dataclass, asdict, fields, replace
from pathlib import Path
import json
from .atomic import write_json


@dataclass(frozen=True)
class AppSettings:
    precision: str = 'auto'
    tensorrt_optimization_level: int = 3
    dynamic_tensorrt_engine: bool = False
    encoder: str = 'libx264'
    video_encoder_speed: str = 'medium'
    audio_encoder: str = 'copy_audio'
    subtitle_encoder: str = 'copy_subtitle'
    audio_bitrate: str = '192k'
    preview_enabled: bool = True
    scene_change_detection_method: str = 'sudo_scene_detect'
    scene_change_detection_enabled: bool = True
    scene_change_detection_threshold: float = 3.5
    discord_rich_presence: bool = False
    video_quality: str = 'High'
    output_folder_location: str = ''
    use_same_output_folder_as_input_file_enabled: bool = False
    last_input_folder_location: str = ''
    uhd_mode: bool = True
    ncnn_gpu_id: int = 0
    pytorch_gpu_id: int = 0
    auto_border_cropping: bool = False
    video_container: str = 'mkv'
    video_pixel_format: str = 'yuv420p'
    pytorch_version: str = '2.9.0'
    pytorch_backend: str = 'CUDA'
    auto_hdr_mode: bool = True


class Settings:
    def __init__(self, path=None, output_folder=None):
        if path is None:
            from .Util import currentDirectory, FileHandler
            path = Path(currentDirectory()) / "settings.json"
            output_folder = FileHandler.getDefaultOutputFolder()
        self.path = Path(path)
        self.defaults = replace(AppSettings(), output_folder_location=output_folder or "",
                                last_input_folder_location=output_folder or "")
        self.values = self.defaults
        self.readSettings()

    def readSettings(self):
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if set(data) != {f.name for f in fields(AppSettings)}:
            raise ValueError("Invalid settings.json; reset application settings")
        for f in fields(AppSettings):
            if type(data[f.name]) is not f.type:
                raise ValueError(f"Invalid setting: {f.name}")
        self.values = AppSettings(**data)

    def writeSetting(self, setting, value):
        self.update(**{setting: value})

    def update(self, **changes):
        types = {f.name: f.type for f in fields(AppSettings)}
        for setting, value in changes.items():
            if types[setting] is bool:
                if value not in (True, False, "True", "False"):
                    raise ValueError(setting)
                changes[setting] = value is True or value == "True"
            else:
                changes[setting] = types[setting](value)
        updated = replace(self.values, **changes)
        if updated != self.values:
            write_json(self.path, asdict(updated))
            self.values = updated

    def writeDefaultSettings(self):
        self.values = self.defaults
        self.writeOutCurrentSettings()

    def writeOutCurrentSettings(self):
        write_json(self.path, asdict(self.values))
