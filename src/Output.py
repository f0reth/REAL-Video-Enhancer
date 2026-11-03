"""Reservations and non-clobbering publication of job-owned output files."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import os
import tempfile


class ConfirmationRequired(Exception):
    pass


def normalized(path):
    return os.path.normcase(str(Path(path).resolve()))


def same_file(first, second):
    return normalized(first) == normalized(second) or (
        os.path.exists(first) and os.path.exists(second) and os.path.samefile(first, second))


def publish_no_replace(source, target):
    if os.name == "nt":
        # Windows rename fails atomically if the destination already exists.
        os.rename(source, target)
        return True
    else:
        os.link(source, target)
        return False


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    modified: int
    digest: str

    @classmethod
    def read(cls, path):
        try:
            with open(path, "rb") as stream:
                stat = os.fstat(stream.fileno())
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                after = os.fstat(stream.fileno())
            if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ConfirmationRequired(f"Output changed while checking: {path}")
            return cls(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, digest)
        except FileNotFoundError:
            return None


class OutputReservation:
    def __init__(self, source, target):
        self.source = str(Path(source).resolve(strict=True))
        # Preserve the final component so a symlink is never silently replaced.
        target = Path(target).absolute()
        self.target = target.parent.resolve() / target.name
        self.approved = None
        self.temporary = None
        self.backup = None
        self.published = False
        self.check_source()
        fd, probe = tempfile.mkstemp(prefix=".rve-write-check-", dir=self.target.parent)
        os.close(fd)
        os.unlink(probe)

    def check_source(self):
        if same_file(self.source, self.target):
            raise ValueError("Output is the input file (including links)")
        if self.target.is_symlink():
            raise ValueError("Output must not be a symbolic link")

    def approve(self, identity):
        # The caller must show this exact identity's path before granting consent.
        self.approved = identity

    def check(self):
        self.check_source()
        if FileIdentity.read(self.target) != self.approved:
            raise ConfirmationRequired(str(self.target))

    def create_temporary(self):
        self.check()
        fd, path = tempfile.mkstemp(prefix=".rve-", suffix=self.target.suffix, dir=self.target.parent)
        os.close(fd)
        self.temporary = Path(path)
        return path

    def commit(self, cancelled=None):
        if self.published:
            self._finish_publication()
            return
        self.check()
        if cancelled and cancelled.is_set():
            raise InterruptedError("Publication cancelled")
        if not self.temporary or not self.temporary.is_file() or self.temporary.stat().st_size == 0:
            raise ValueError("Missing or empty output")
        if self.approved is not None:
            fd, backup = tempfile.mkstemp(prefix=".rve-replaced-", dir=self.target.parent)
            os.close(fd)
            self.backup = Path(backup)
            try:
                os.replace(self.target, self.backup)
            except BaseException:
                self.backup.unlink()
                self.backup = None
                raise
            if FileIdentity.read(self.backup) != self.approved:
                self._restore()
                raise ConfirmationRequired("Output changed during publication")
        try:
            # Atomic fail-if-exists: a file created after check() is never overwritten.
            moved = publish_no_replace(self.temporary, self.target)
        except BaseException:
            self._restore()
            raise
        self.published = True
        if moved:
            self.temporary = None
        self._finish_publication()

    def _finish_publication(self):
        if self.temporary:
            self.temporary.unlink()
            self.temporary = None
        if self.backup:
            self.backup.unlink()
            self.backup = None

    def _restore(self):
        if self.backup:
            try:
                moved = publish_no_replace(self.backup, self.target)
            except FileExistsError:
                raise OSError(f"Target changed; previous file preserved at {self.backup}")
            if not moved:
                self.backup.unlink()
            self.backup = None

    def cleanup(self):
        if self.published:
            self._finish_publication()
            return
        if self.temporary:
            self.temporary.unlink(missing_ok=True)
            self.temporary = None


class Reservations:
    def __init__(self):
        self.entries = {}

    def reserve(self, job_id, source, target):
        for owner, entry in self.entries.items():
            if owner != job_id and same_file(entry.target, target):
                raise ValueError(f"Output already reserved: {target}")
        reservation = OutputReservation(source, target)
        self.entries[job_id] = reservation
        return reservation

    def release(self, job_id):
        self.entries.pop(job_id, None)
