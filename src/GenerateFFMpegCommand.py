"""Structured encode settings and pure FFmpeg argument generation."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EncodingSettings:
    codec: str = "libx264"
    quality: int | None = 18
    preset: str | None = "medium"
    profile: int | None = None
    pixel_format: str = "yuv420p"
    audio_codec: str = "copy"
    audio_bitrate: str = "192k"
    subtitle_codec: str = "copy"
    color_space: str | None = None
    color_primaries: str | None = None
    color_transfer: str | None = None
    lossless: bool = False
    hdr: bool = False

    def validate(self):
        if self.codec not in ("libx264", "libx265", "libvpx-vp9", "libsvtav1", "h264_nvenc", "hevc_nvenc", "av1_nvenc", "prores_ks", "ffv1", "utvideo"):
            raise ValueError(f"Unsupported encoder: {self.codec}")
        if self.quality is not None and not 0 <= self.quality <= (63 if self.codec in ("libvpx-vp9", "libsvtav1") else 51):
            raise ValueError("Quality is outside the encoder's range")
        if self.codec == "prores_ks" and self.profile not in range(6):
            raise ValueError("ProRes requires profile 0-5")


def build_encoder_command(settings: EncodingSettings):
    settings.validate()
    command = ["-c:v", settings.codec]
    if settings.codec == "prores_ks":
        command += ["-profile:v", str(settings.profile)]
    elif settings.codec not in ("ffv1", "utvideo"):
        mode = "-cq:v" if settings.codec.endswith("_nvenc") else "-crf"
        command += [mode, str(settings.quality)]
        if settings.preset is not None:
            command += ["-cpu-used" if settings.codec == "libvpx-vp9" else "-preset", settings.preset]
    if settings.lossless:
        if settings.codec == "libx264":
            command += ["-qp", "0"]
        elif settings.codec == "libx265":
            command += ["-x265-params", "lossless=1:hdr-opt=1" if settings.hdr else "lossless=1"]
        elif settings.codec == "libvpx-vp9":
            command += ["-lossless", "1"]
    if settings.hdr and settings.codec == "libx265" and not settings.lossless:
        command += ["-x265-params", "hdr-opt=1"]
    command += ["-pix_fmt", settings.pixel_format, "-c:a", settings.audio_codec, "-c:s", settings.subtitle_codec]
    if settings.audio_codec != "copy":
        command += ["-b:a", settings.audio_bitrate]
    for flag, value in (("-colorspace", settings.color_space), ("-color_primaries", settings.color_primaries), ("-color_trc", settings.color_transfer)):
        if value is not None:
            command += [flag, value]
    return command
