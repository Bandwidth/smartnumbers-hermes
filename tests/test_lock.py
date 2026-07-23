import os
import subprocess
import sys

from transcript_listener.lock import SingleInstanceLock


def _run_lock_probe(path: str) -> str:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from transcript_listener.lock import SingleInstanceLock; import sys; lock=SingleInstanceLock(sys.argv[1]); print(lock.acquire()); lock.release()",
            path,
        ],
        cwd=os.getcwd(),
        env={**os.environ, "PYTHONPATH": "."},
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def test_lock_ignores_stale_file(tmp_path):
    path = tmp_path / "transcripts.lock"
    path.write_text("dead-pid")
    lock = SingleInstanceLock(path)

    assert lock.acquire() is True
    assert path.read_text() != "dead-pid"

    lock.release()
    assert path.exists()


def test_lock_blocks_another_live_process(tmp_path):
    path = tmp_path / "transcripts.lock"
    lock = SingleInstanceLock(path)
    assert lock.acquire() is True

    try:
        assert _run_lock_probe(str(path)) == "False"
    finally:
        lock.release()

    assert _run_lock_probe(str(path)) == "True"
