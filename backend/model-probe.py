"""Inspect a local upscale model using the same loaders as inference."""
import sys
import hashlib
from pathlib import Path
from src.notifications import initialize, emit
from src.lifecycle import install, cleanup


def fingerprints(path):
    root = Path(path).resolve(strict=True)
    paths = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]
    result = []
    for path in paths:
        with path.open("rb") as stream:
            result.append({"path": str(path.resolve()), "digest": hashlib.file_digest(stream, "sha256").hexdigest()})
    return result

if __name__ == "__main__":
    initialize()
    try:
        install()
        backend, path = sys.argv[1:]
        files = fingerprints(path)
        if backend == "ncnn":
            from src.ncnn.UpscaleNCNN import getNCNNScale
            scale = getNCNNScale(path)
        elif backend == "pytorch":
            import torch
            from src.pytorch.UpscaleModelWrapper import UpscaleModelWrapper
            model = UpscaleModelWrapper(path, torch.device("cpu"), torch.float32)
            scale = model.get_scale()
        else:
            raise ValueError("Unsupported local model backend")
        if files != fingerprints(path):
            raise ValueError("Model changed during inspection")
        emit("model", scale=scale, files=files)
        cleanup()
    except BaseException as error:
        emit("error", message=str(error))
        cleanup()
        raise
