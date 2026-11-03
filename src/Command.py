"""Pure command generation; no environment detection, downloads or mutation."""
from dataclasses import dataclass
import os
import shlex
from .GenerateFFMpegCommand import build_encoder_command

from .Jobs import RenderOptions


@dataclass(frozen=True)
class RuntimePaths:
    python: str
    backend: str
    models: str
    custom_models: str
    cwd: str
    ffmpeg: str


def build_command(options: RenderOptions, paths: RuntimePaths, output: str,
                  pause_memory: str, preview_memory: str | None = None):
    options.validate()
    settings = options.execution
    backend = options.backend.split()[0]
    command = [paths.python, "-u", os.path.join(paths.backend, "rve-backend.py"),
               "-i", options.inputFile, "-o", output, "-b", backend,
               "--precision", settings.precision,
               "--custom_encoder", " " + shlex.join(build_encoder_command(options.encoding)) + " ",
               "--tensorrt_opt_profile", str(settings.tensorrt_optimization_level),
               "--pause_shared_memory_id", pause_memory,
               "--ncnn_gpu_id", str(settings.ncnn_gpu_id),
               "--pytorch_gpu_id", str(settings.pytorch_gpu_id),
               "--cwd", paths.cwd, "--ffmpeg_path", paths.ffmpeg, "--overwrite"]
    if "(" in options.backend:
        device = options.backend.split("(")[1].rstrip(")").lower()
        command += ["--device", "cuda" if device == "rocm" else device]
    for value, flag in ((options.startTime, "--start_time"), (options.endTime, "--end_time")):
        if value is not None:
            command += [flag, str(value)]
    for model in options.models:
        flag = {"upscale": "--upscale_model", "interpolate": "--interpolate_model",
                "scene": "--scene_detect_model", "deblur": "--extra_restoration_models",
                "denoise": "--extra_restoration_models", "decompress": "--extra_restoration_models"}[model.kind]
        command += [flag, model.path]
    if any(m.kind == "upscale" for m in options.models):
        command += ["--override_upscale_scale", str(options.processing.upscale_factor)]
    if any(m.kind == "interpolate" for m in options.models):
        command += ["--interpolate_factor", str(options.processing.interpolate_factor)]
    if options.processing.tiling_enabled:
        command += ["--tilesize", str(options.processing.tile_size)]
    command += ["--scene_detect_method", settings.scene_change_detection_method if settings.scene_change_detection_enabled else "none",
                "--scene_detect_threshold", str(settings.scene_change_detection_threshold)]
    for enabled, flag in ((options.processing.slow_motion, "--slomo_mode"),
                          (options.processing.dynamic_flow, "--dynamic_scaled_optical_flow"),
                          (options.processing.ensemble, "--ensemble"), (options.processing.benchmark, "--benchmark"),
                          (options.processing.hdr, "--hdr_mode"),
                          (settings.auto_border_cropping, "--border_detect"),
                          (settings.dynamic_tensorrt_engine, "--tensorrt_dynamic_shapes"),
                          (settings.uhd_mode and (options.video.width > 1920 or options.video.height > 1080), "--UHD_mode")):
        if enabled:
            command.append(flag)
    if settings.preview_enabled and preview_memory:
        command += ["--preview_shared_memory_id", preview_memory]
    return command
