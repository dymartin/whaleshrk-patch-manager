"""Card transport over the system OpenSSH client."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import PurePosixPath

from .base import TransportPathError, normalize_path

# ServerAliveInterval/CountMax only catch a dead *connection* -- sshd still
# answering keepalives while the remote command itself blocks (e.g. a stuck
# SD card write) leaves a session that looks alive forever. This bounds the
# command itself. Generous because a write can carry a whole module archive
# or sample set over a slow link; every op here runs inside push's staged
# transaction, so a timeout here is always safe to retry.
COMMAND_TIMEOUT_SECONDS = 300


class SshTransportError(RuntimeError):
    pass


class SshTransport:
    def __init__(self, host: str = "organelle", root: str = "/sdcard") -> None:
        self.host = host
        self.root = PurePosixPath(root)
        if not self.root.is_absolute():
            raise TransportPathError("SSH card root must be absolute")

    def _path(self, path: str) -> str:
        return str(self.root.joinpath(*normalize_path(path).split("/")))

    def _run(self, command: str, data: bytes | None = None, *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(
                [
                    "ssh", "-T",
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=10",
                    "-o", "ServerAliveInterval=5",
                    "-o", "ServerAliveCountMax=3",
                    self.host, command,
                ],
                input=data,
                capture_output=True,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise SshTransportError(
                f"command timed out after {COMMAND_TIMEOUT_SECONDS}s with no response from the device "
                f"(command: {command!r}) -- the SSH connection was alive but the remote side never "
                "returned; the device likely needs a power cycle"
            ) from exc
        except (FileNotFoundError, OSError) as exc:
            raise SshTransportError(f"could not run ssh: {exc}") from exc
        if check and result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip() or f"exit {result.returncode}"
            raise SshTransportError(detail)
        return result

    def exists(self, path: str) -> bool:
        result = self._run(f"test -e {shlex.quote(self._path(path))}", check=False)
        if result.returncode not in (0, 1):
            raise SshTransportError(result.stderr.decode("utf-8", errors="replace").strip())
        return result.returncode == 0

    def list(self, path: str) -> list[str]:
        target = str(self.root) if not path else self._path(path)
        command = f"test ! -d {shlex.quote(target)} || find {shlex.quote(target)} -mindepth 1 -maxdepth 1 -printf '%f\\0'"
        output = self._run(command).stdout
        return sorted(name for name in output.decode("utf-8").split("\0") if name)

    def read(self, path: str) -> bytes:
        target = self._path(path)
        if not self.exists(path):
            raise FileNotFoundError(path)
        return self._run(f"test -f {shlex.quote(target)} && cat {shlex.quote(target)}").stdout

    def write(self, path: str, data: bytes) -> None:
        target = self._path(path)
        parent = str(PurePosixPath(target).parent)
        self._run(f"test ! -d {shlex.quote(target)} && mkdir -p {shlex.quote(parent)} && tee {shlex.quote(target)} >/dev/null", data)

    def delete(self, path: str) -> None:
        target = self._path(path)
        if not self.exists(path):
            raise FileNotFoundError(path)
        self._run(f"rm -rf -- {shlex.quote(target)}")

    def mkdir(self, path: str) -> None:
        target = self._path(path)
        self._run(f"test ! -f {shlex.quote(target)} && mkdir -p {shlex.quote(target)}")

    def rename(self, source: str, target: str) -> None:
        source_path = self._path(source)
        target_path = self._path(target)
        if not self.exists(source):
            raise FileNotFoundError(source)
        parent = str(PurePosixPath(target_path).parent)
        self._run(
            f"rm -rf -- {shlex.quote(target_path)} && mkdir -p {shlex.quote(parent)} && "
            f"mv -- {shlex.quote(source_path)} {shlex.quote(target_path)}"
        )

    def flush(self) -> None:
        self._run("sync")

    def check_sha1_manifest(self, manifest: bytes) -> str | None:
        """Run the card's native manifest check in one SSH round trip."""
        patches = self.root / "Patches"
        result = self._run(f"cd {shlex.quote(str(patches))} && sha1sum -c -", manifest, check=False)
        if result.returncode == 0:
            return None
        return (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()
