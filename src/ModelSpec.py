"""Model identity and immutable, verified local file references."""
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
import json
import uuid

from .atomic import write_json


@dataclass(frozen=True)
class ModelFile:
    path: str
    digest: str

    @classmethod
    def inspect(cls, path):
        path = Path(path).resolve(strict=True)
        with path.open("rb") as stream:
            digest = sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return cls(str(path), digest.hexdigest())

    def verify(self):
        if self != self.inspect(self.path):
            raise ValueError(f"Model changed; register it again: {self.path}")


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    kind: str
    path: str
    scale: int
    backends: tuple[str, ...]
    options: tuple[str, ...] = ()
    download: str | None = None
    files: tuple[ModelFile, ...] = ()

    def verify(self):
        if not self.files and self.download is None:
            raise ValueError(f"Unverified local model: {self.name}")
        for file in self.files:
            file.verify()
        if self.files and Path(self.path).is_dir():
            actual = {str(p.resolve()) for p in Path(self.path).rglob("*") if p.is_file()}
            if actual != {f.path for f in self.files}:
                raise ValueError(f"Model file set changed: {self.path}")

    @classmethod
    def from_dict(cls, value):
        return cls(**{**value, "backends": tuple(value["backends"]),
                      "options": tuple(value["options"]),
                      "files": tuple(ModelFile(**f) for f in value["files"])})


class ModelRegistry:
    def __init__(self, path):
        self.path = Path(path)
        self.models = {}
        if self.path.exists():
            self.models = {m.id: m for m in map(ModelSpec.from_dict, json.loads(self.path.read_text(encoding="utf-8")))}

    def register(self, model):
        model.verify()
        if model.scale < 1 or not model.backends or model.download:
            raise ValueError("Registration requires a verified local model")
        self.models[model.id] = model
        self.save()

    def remove(self, model_id):
        del self.models[model_id]
        self.save()  # References only; never delete model files.

    def save(self):
        write_json(self.path, [asdict(m) for m in self.models.values()])


def local_model(path, backend, scale, options=()):
    """Called only after the backend has successfully inspected architecture/scale."""
    path = Path(path).resolve(strict=True)
    if type(scale) is not int or scale < 1:
        raise ValueError("Model scale could not be determined")
    paths = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    if backend == "ncnn":
        required = {path / (path.name + ext) for ext in (".param", ".bin")}
        if not required.issubset(paths):
            raise ValueError("NCNN requires matching directory/name.param and name.bin")
    return ModelSpec(str(uuid.uuid4()), path.name, "upscale", str(path), scale,
                     ("pytorch", "tensorrt") if backend == "pytorch" else (backend,),
                     tuple(options), files=tuple(ModelFile.inspect(p) for p in paths))
