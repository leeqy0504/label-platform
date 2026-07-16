from collections.abc import Sequence
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Protocol


class ProcessHandle(Protocol):
    @property
    def pid(self) -> int: ...

    def wait(self) -> int: ...

    def stop(self, timeout_seconds: float) -> None: ...


class ProcessLauncher(Protocol):
    def launch(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        log_path: Path,
    ) -> ProcessHandle: ...


class SubprocessHandle:
    def __init__(self, process: subprocess.Popen[bytes]):
        self.process = process

    @property
    def pid(self) -> int:
        return self.process.pid

    def wait(self) -> int:
        return self.process.wait()

    def stop(self, timeout_seconds: float) -> None:
        if self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=timeout_seconds)
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=timeout_seconds)


class SubprocessLauncher:
    def launch(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        log_path: Path,
    ) -> ProcessHandle:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab", buffering=0) as log:
            process = subprocess.Popen(
                list(command),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        return SubprocessHandle(process)


class RecoveredProcessHandle:
    def __init__(self, pid: int, expected_command_fragment: str):
        self._pid = pid
        self.expected_command_fragment = expected_command_fragment

    @property
    def pid(self) -> int:
        return self._pid

    def wait(self) -> int:
        while self._matches_process():
            time.sleep(1)
        return 0

    def stop(self, timeout_seconds: float) -> None:
        if not self._matches_process():
            return
        try:
            os.killpg(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout_seconds
        while self._matches_process() and time.monotonic() < deadline:
            time.sleep(0.1)
        if self._matches_process():
            os.killpg(self.pid, signal.SIGKILL)

    def _matches_process(self) -> bool:
        result = subprocess.run(
            ["ps", "-p", str(self.pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and self.expected_command_fragment in result.stdout


def recover_process(pid: int, run_id: str) -> ProcessHandle | None:
    handle = RecoveredProcessHandle(pid, f"unitrain_api.worker --run-id {run_id}")
    return handle if handle._matches_process() else None
