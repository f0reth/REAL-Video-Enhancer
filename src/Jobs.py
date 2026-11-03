"""Values owned by an editor/job, separate from mutable execution state."""
from dataclasses import dataclass, field
from enum import Enum
import math
import uuid

from .ModelSpec import ModelSpec
from .GenerateFFMpegCommand import EncodingSettings


@dataclass(frozen=True)
class ExecutionSettings:
    precision: str = "auto"
    tensorrt_optimization_level: int = 3
    dynamic_tensorrt_engine: bool = False
    ncnn_gpu_id: int = 0
    pytorch_gpu_id: int = 0
    auto_border_cropping: bool = False
    preview_enabled: bool = True
    scene_change_detection_enabled: bool = True
    scene_change_detection_method: str = "sudo_scene_detect"
    scene_change_detection_threshold: float = 3.5
    uhd_mode: bool = True


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frame_count: int


@dataclass(frozen=True)
class ProcessingSettings:
    tiling_enabled: bool = False
    tile_size: int = 0
    interpolate_factor: float = 1
    upscale_factor: int = 1
    benchmark: bool = False
    slow_motion: bool = False
    dynamic_flow: bool = False
    ensemble: bool = False
    hdr: bool = False


@dataclass(frozen=True)
class RenderOptions:
    inputFile: str
    outputPath: str
    video: VideoInfo
    processing: ProcessingSettings = field(default_factory=ProcessingSettings)
    backend: str = "pytorch"
    startTime: float | None = None
    endTime: float | None = None
    isPreview: bool = False
    encoding: EncodingSettings = field(default_factory=EncodingSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    models: tuple[ModelSpec, ...] = ()

    def validate(self):
        self.encoding.validate()
        backend = self.backend.split()[0]
        if backend not in ("pytorch", "tensorrt", "ncnn"):
            raise ValueError(f"Unsupported backend: {backend}")
        if not math.isfinite(self.video.fps) or self.video.fps <= 0 or self.video.frame_count <= 0 or self.video.width <= 0 or self.video.height <= 0:
            raise ValueError("Invalid video duration/FPS")
        start = self.startTime if self.startTime is not None else 0
        end = self.endTime if self.endTime is not None else self.video.frame_count / self.video.fps
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= self.video.frame_count / self.video.fps + 1 / self.video.fps:
            raise ValueError("Invalid video interval")
        if backend == "ncnn" and self.processing.hdr:
            raise ValueError("NCNN does not support HDR")
        if self.processing.upscale_factor < 1 or not math.isfinite(self.processing.interpolate_factor) or self.processing.interpolate_factor < 1:
            raise ValueError("Invalid scale")
        if self.processing.tile_size < 0 or self.execution.precision not in ("auto", "float16", "float32"):
            raise ValueError("Invalid tile size or precision")
        if not 0 <= self.execution.tensorrt_optimization_level <= 5 or min(self.execution.ncnn_gpu_id, self.execution.pytorch_gpu_id) < 0:
            raise ValueError("Invalid execution device/profile")
        if self.processing.dynamic_flow and self.execution.uhd_mode and (self.video.width > 1920 or self.video.height > 1080):
            raise ValueError("Dynamic optical flow cannot be combined with UHD mode")
        for model in self.models:
            if backend not in model.backends:
                raise ValueError(f"{model.name} does not support {backend}")
            if model.kind == "interpolate":
                for enabled, option in ((self.processing.ensemble, "ensemble"), (self.processing.dynamic_flow, "dynamic_flow")):
                    if enabled and option not in model.options:
                        raise ValueError(f"{model.name} does not support {option}")


class JobState(str, Enum):
    WAITING = "waiting"
    PREPARING = "preparing"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    AWAITING_REPLACEMENT = "awaiting_replacement"
    FINALIZING = "finalizing"
    FINALIZE_FAILED = "finalize_failed"
    COMPLETED = "completed"


@dataclass
class Job:
    options: RenderOptions
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: JobState = JobState.WAITING
    error: str = ""
    progress: dict = field(default_factory=dict)
    effective: dict = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    output: object = None
    pending_identity: object = None
