"""Subprocess helpers shared by the headless CLI wrapper and the live-session launcher.

Three jobs, all about running Inkscape safely on every OS:

* start the child in its own process group/session, so a timeout can kill the *tree*
  (Inkscape spawns Python for extensions; killing only the parent orphans those children),
* cap an oversized open-file limit (Inkscape 1.4.2 on macOS segfaults when extensions run
  with a ~1M soft ``RLIMIT_NOFILE``: glib sizes a stack array by it),
* on macOS, put the app bundle's ``bin`` on ``PATH`` so extensions find Python (the
  ``Inkscape.app`` launcher script does this; running ``Contents/MacOS/inkscape`` skips it).

The process-tree handling follows the approach in grumpydevorg/inkscape-mcps (MIT); see NOTICE.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_SOFT_NOFILE = 4096
_WIN_NEW_PROCESS_GROUP = 0x00000200  # CREATE_NEW_PROCESS_GROUP
_WIN_DETACHED = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW


def cap_open_file_limit() -> None:
    """Child-side (preexec) hook: lower an oversized soft ``RLIMIT_NOFILE`` before exec.

    Dev tools and IDE hosts commonly hand children 1,048,576 while a normal launch has 256.
    Only the soft limit is touched; the hard limit is left alone. POSIX only.
    """
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == resource.RLIM_INFINITY or soft > MAX_SOFT_NOFILE:
        target = MAX_SOFT_NOFILE if hard == resource.RLIM_INFINITY else min(MAX_SOFT_NOFILE, hard)
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))


def add_bundled_tools_to_path(env: dict[str, str], inkscape_exe: str | None) -> None:
    """macOS: prepend ``Inkscape.app/Contents/Resources/bin`` (bundled python3) to ``PATH``."""
    if sys.platform != "darwin" or not inkscape_exe:
        return
    try:
        bundled = Path(inkscape_exe).resolve().parent.parent / "Resources" / "bin"
    except OSError:
        return
    if bundled.is_dir():
        env["PATH"] = f"{bundled}{os.pathsep}{env.get('PATH', '')}"


def child_kwargs(*, detached: bool = False) -> dict[str, Any]:
    """Popen/``create_subprocess_exec`` kwargs: own process group + sane fd limit.

    ``detached=True`` is for a long-lived GUI that must outlive this server (Windows: no
    console, detached; POSIX: new session either way).
    """
    if sys.platform == "win32":
        return {"creationflags": _WIN_DETACHED if detached else _WIN_NEW_PROCESS_GROUP}
    return {"start_new_session": True, "preexec_fn": cap_open_file_limit}


def _signal_group(pid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(pid), sig)


async def terminate_process_tree(proc: asyncio.subprocess.Process, grace_s: float = 2.0) -> None:
    """Stop ``proc`` and everything it spawned: polite first, then forceful."""
    if proc.returncode is not None:
        return
    if sys.platform == "win32":
        # taskkill /T walks the child tree; /F because GUI apps ignore a polite close here.
        with contextlib.suppress(OSError):
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/T",
                "/F",
                "/PID",
                str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
    else:
        _signal_group(proc.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=grace_s)
            return
        except TimeoutError:
            _signal_group(proc.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    await proc.wait()


def terminate_popen_tree(proc: subprocess.Popen[Any], grace_s: float = 2.0) -> None:
    """Blocking twin of :func:`terminate_process_tree` for ``subprocess.Popen`` children."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        with contextlib.suppress(OSError):
            subprocess.run(  # noqa: S603 - fixed argv
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],  # noqa: S607
                capture_output=True,
                check=False,
                timeout=10,
            )
    else:
        _signal_group(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=grace_s)
            return
        except subprocess.TimeoutExpired:
            _signal_group(proc.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    proc.wait()
