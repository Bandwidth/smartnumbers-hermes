"""Single-instance lock for profile-owned background ingestion."""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path


class SingleInstanceLock:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            try:
                os.close(fd)
            except UnboundLocalError:
                pass
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                return False
            raise
        self._fd = fd
        os.ftruncate(self._fd, 0)
        os.write(self._fd, str(os.getpid()).encode("ascii", errors="ignore"))
        return True

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "SingleInstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
