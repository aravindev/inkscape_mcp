"""Security policy for the Inkscape MCP server.

What this adds, and what it deliberately does not:

* **Path scoping that is actually enforced.** ``allowed_directories`` has always been a config
  field (and is mentioned to the agent), but nothing read it. :class:`SecurityMiddleware` now
  vets every path argument of every ``inkscape_*`` tool in one place, resolves symlinks, and
  rewrites the argument to the vetted absolute path so the tool uses exactly what was checked.
  With no allowed directories configured, behaviour is unchanged (permissive).
* **Action-chain vetting** (always on): Inkscape action chains are ``;``-joined, so a value
  containing ``;`` or a newline would inject extra actions. Rejected before they reach Inkscape.
* **Atomic outputs** and **file-size limits**.
* **Strict mode** (opt-in): a raw-action allowlist, no arbitrary-Python ``execute_inkex``, and
  only stock ``org.inkscape.*`` extensions, on top of mandatory path scoping.

The path-scoping, size-check, action-allowlist and atomic-write ideas come from
grumpydevorg/inkscape-mcps (MIT); this is a re-implementation around this server's async
wrapper and tool layout. See NOTICE.md.

Configuration (config file field, overridable by env):
  allowed_directories  /  INKSCAPE_MCP_ALLOWED_DIRS   (os.pathsep-separated)
  security_mode        /  INKSCAPE_MCP_SECURITY       ("permissive" | "strict")
  max_file_size_mb     (existing)
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SECURITY_ENV = "INKSCAPE_MCP_SECURITY"
ALLOWED_DIRS_ENV = "INKSCAPE_MCP_ALLOWED_DIRS"

# Tool arguments that carry a filesystem path. ``target`` is only a path for live ``open_file``.
_PATH_ARGS = ("input_path", "output_path", "input_file", "output_file", "output_dir")
_PATH_LIST_ARGS = ("input_paths",)

# Keys inside JSON parameters whose string values are filesystem paths.
_PATH_KEY_HINTS = ("path", "file", "dir", "folder", "output", "input", "export", "save", "target")

_ACTION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FORBIDDEN_IN_ACTION = (";", "\n", "\r", "\0")

# Strict mode: raw user-supplied actions (live ``apply_action``) must start with one of these ...
_STRICT_ALLOW_PREFIXES = (
    "select",
    "unselect",
    "selection-",
    "object-",
    "path-",
    "transform-",
    "query-",
    "layer-",
    "edit-undo",
    "edit-redo",
    "edit-select",
    "edit-delete",
    "edit-duplicate",
    "edit-copy",
    "edit-paste",
    "edit-cut",
    "delete-selection",
    "fit-canvas",
    "page-",
    "zoom-",
    "view-",
)
# ... and must not be any of these (file/export write anywhere; extensions run arbitrary code).
_STRICT_DENY_PREFIXES = ("file-", "export-", "window-", "org.", "com.", "extension", "dialog-")
_STRICT_BLOCKED_OPS = {("inkscape_live", "execute_inkex"), ("inkscape_system", "execute_extension")}


class SecurityError(Exception):
    """A request was refused by policy. The message is safe to show to the caller."""


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


# ---------------------------------------------------------------------------- policy


@dataclass(frozen=True)
class SecurityPolicy:
    allowed_dirs: tuple[Path, ...] = ()
    max_file_bytes: int = 100 * 1024 * 1024
    strict: bool = False

    @property
    def restricted(self) -> bool:
        return bool(self.allowed_dirs)

    # -- construction
    @classmethod
    def from_config(cls, cfg: Any) -> SecurityPolicy:
        """Build the policy from a loaded ``InkscapeConfig`` plus env overrides."""
        mode = (os.environ.get(SECURITY_ENV) or getattr(cfg, "security_mode", "permissive") or "permissive").lower()
        if mode not in ("permissive", "strict"):
            log.warning("Ignoring invalid %s=%r; using permissive", SECURITY_ENV, mode)
            mode = "permissive"
        strict = mode == "strict"

        env_dirs = os.environ.get(ALLOWED_DIRS_ENV)
        raw_dirs = (
            [d for d in env_dirs.split(os.pathsep) if d]
            if env_dirs
            else list(getattr(cfg, "allowed_directories", []) or [])
        )
        dirs: list[Path] = []
        for d in raw_dirs:
            try:
                dirs.append(Path(d).expanduser().resolve())
            except (OSError, RuntimeError):
                log.warning("Ignoring unusable allowed directory %r", d)
        if strict and not dirs:
            # Strict without an explicit scope must not silently mean "everywhere".
            dirs = [Path.cwd().resolve()]
            log.warning("security_mode=strict with no allowed_directories: scoping to %s", dirs[0])

        mb = getattr(cfg, "max_file_size_mb", 100)
        return cls(allowed_dirs=tuple(dict.fromkeys(dirs)), max_file_bytes=int(mb) * 1024 * 1024, strict=strict)

    # -- paths
    def resolve_path(self, raw: str, *, role: str = "input") -> Path:
        """Vet ``raw`` and return the absolute, symlink-resolved path to use instead.

        ``role`` is ``input`` (existing files are size-checked), ``output`` or ``dir``.
        """
        if "\0" in raw:
            raise SecurityError("path contains a NUL byte")
        p = Path(raw).expanduser()
        if not p.is_absolute():
            # Under a scope, relative paths live inside it (first directory); otherwise as before.
            p = (self.allowed_dirs[0] if self.restricted else Path.cwd()) / p
        try:
            resolved = p.resolve()
        except (OSError, RuntimeError) as exc:  # e.g. symlink loop
            raise SecurityError(f"cannot resolve path {raw!r}: {exc}") from exc

        if self.restricted and not any(_is_within(resolved, root) for root in self.allowed_dirs):
            shown = ", ".join(str(d) for d in self.allowed_dirs)
            raise SecurityError(f"path {raw!r} is outside the allowed directories ({shown})")

        if role == "input":
            self.check_size(resolved)
        return resolved

    def check_size(self, path: Path) -> None:
        try:
            if path.is_file() and path.stat().st_size > self.max_file_bytes:
                mb = self.max_file_bytes // (1024 * 1024)
                raise SecurityError(f"file {path.name!r} exceeds the {mb} MB limit")
        except OSError:
            return  # unreadable/missing: the tool reports that itself

    # -- actions
    def check_raw_action(self, action: str) -> None:
        """Vet a user-supplied raw action. Chain-safety always; the allowlist in strict mode."""
        validate_action_chain([action])
        if not self.strict:
            return
        name = action.split(":", 1)[0].strip()
        if any(name.startswith(p) for p in _STRICT_DENY_PREFIXES) or not any(
            name.startswith(p) for p in _STRICT_ALLOW_PREFIXES
        ):
            raise SecurityError(f"action {name!r} is not permitted in strict security mode")

    def check_extension(self, ext_id: str) -> None:
        if self.strict and not ext_id.startswith("org.inkscape."):
            raise SecurityError(
                f"extension {ext_id!r} is not permitted in strict security mode (stock org.inkscape.* only)"
            )

    def _vetted(self, raw: str, role: str) -> str:
        """Check ``raw``; hand back the vetted absolute path under a scope, else the original text.

        Without a scope the checks (NUL byte, size) still run but the argument is passed through
        untouched, so a tool's own handling of relative paths is unchanged.
        """
        resolved = self.resolve_path(raw, role=role)
        return str(resolved) if self.restricted else raw

    # -- paths nested inside JSON parameters
    def _looks_like_path(self, key: str, value: str) -> bool:
        """Heuristic for free-form params: a path-ish key, or any value that is plainly absolute."""
        if not value or "\n" in value or len(value) > 4096:
            return False
        k = key.lower()
        if any(h in k for h in _PATH_KEY_HINTS) and (os.sep in value or "/" in value or value.startswith(("~", "."))):
            return True
        return os.path.isabs(value) or value.startswith("~")

    def vet_json_paths(self, data: Any, *, key: str = "") -> Any:
        """Walk a decoded JSON value, vetting and rewriting every path-looking string in it."""
        if isinstance(data, dict):
            return {k: self.vet_json_paths(v, key=str(k)) for k, v in data.items()}
        if isinstance(data, list):
            return [self.vet_json_paths(v, key=key) for v in data]
        if isinstance(data, str) and self._looks_like_path(key, data):
            role = "output" if any(h in key.lower() for h in ("output", "export", "save")) else "input"
            return str(self.resolve_path(data, role=role))
        return data

    # -- whole tool calls
    def vet_call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Return the arguments to actually run with (paths rewritten), or raise SecurityError."""
        out = dict(args)
        op = str(args.get("operation", ""))

        if self.strict and (tool, op) in _STRICT_BLOCKED_OPS:
            raise SecurityError(f"{tool}.{op} is disabled in strict security mode")

        for key in _PATH_ARGS:
            val = out.get(key)
            if isinstance(val, str) and val:
                role = "dir" if key == "output_dir" else "output" if key.startswith("output") else "input"
                out[key] = self._vetted(val, role)
        for key in _PATH_LIST_ARGS:
            vals = out.get(key)
            if isinstance(vals, list):
                out[key] = [self._vetted(v, "input") if isinstance(v, str) and v else v for v in vals]

        target = out.get("target")
        if tool == "inkscape_live" and op == "open_file" and isinstance(target, str) and target:
            out["target"] = self._vetted(target, "input")
        if tool == "inkscape_live" and op == "apply_action" and isinstance(target, str) and target:
            self.check_raw_action(target)
        if tool == "inkscape_extension" and op in ("run", "run_live") and isinstance(target, str) and target:
            self.check_extension(target)

        # Paths can also hide inside JSON-valued parameters: rasterize's ``filename``, extension
        # parameters for export-style extensions. Only matters when a scope is set.
        if self.restricted:
            for key in ("payload", "params"):
                raw = out.get(key)
                if not isinstance(raw, str) or not raw.lstrip().startswith(("{", "[")):
                    continue
                if key == "payload" and not (tool == "inkscape_live" and op == "rasterize"):
                    continue  # other payloads are SVG/XPath/code, not path-bearing JSON
                try:
                    out[key] = json.dumps(self.vet_json_paths(json.loads(raw)))
                except json.JSONDecodeError:
                    continue  # the tool reports malformed JSON itself
            ext_params = out.get("extension_params")
            if isinstance(ext_params, dict):
                out["extension_params"] = self.vet_json_paths(ext_params)
        if tool == "inkscape_system" and isinstance(out.get("extension_id"), str) and out["extension_id"]:
            self.check_extension(out["extension_id"])
        return out


# ---------------------------------------------------------------------------- always-on helpers


def validate_action_chain(actions: list[str]) -> None:
    """Reject action strings that could break out of their slot in a ``;``-joined chain.

    Inkscape has no escape for ``;``, so a value containing one silently becomes a second action
    (e.g. ``select-by-id:a;file-open:...``). Names must also look like action names.
    """
    for a in actions:
        if not isinstance(a, str):
            raise SecurityError(f"action must be a string, got {type(a).__name__}")
        if any(ch in a for ch in _FORBIDDEN_IN_ACTION):
            raise SecurityError(f"action {a[:60]!r} contains a forbidden character (';', newline or NUL)")
        name = a.split(":", 1)[0].strip()
        if not _ACTION_NAME_RE.match(name):
            raise SecurityError(f"invalid action name {name[:60]!r}")


@contextlib.contextmanager
def atomic_output(final: str | os.PathLike[str]) -> Iterator[Path]:
    """Yield a sibling temp path; move it over ``final`` only if the block succeeds.

    The temp name keeps ``final``'s suffix, because Inkscape picks the export format from it.
    A crash or timeout therefore never leaves a half-written file at ``final``.
    """
    final_p = Path(final)
    # Inkscape will not create directories, and the temp file lives beside the target.
    final_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = final_p.with_name(f"{final_p.stem}.tmp-{uuid.uuid4().hex[:8]}{final_p.suffix}")
    try:
        yield tmp
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise FileNotFoundError(f"expected output was not produced: {final_p}")
        os.replace(tmp, final_p)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------- middleware


def _denied_result(tool: str, args: dict[str, Any], message: str) -> Any:
    """A tool-shaped failure, so clients parse it exactly like any other tool error."""
    from fastmcp.tools import ToolResult

    payload = {
        "success": False,
        "operation": str(args.get("operation", "")),
        "message": message,
        "data": {},
        "execution_time_ms": 0.0,
        "error": "security policy",
    }
    return ToolResult(content=json.dumps(payload), structured_content=payload)


def make_middleware(policy: SecurityPolicy) -> Any:
    """Build the FastMCP middleware enforcing ``policy`` on every ``inkscape_*`` tool call."""
    from fastmcp.server.middleware import Middleware

    class SecurityMiddleware(Middleware):
        async def on_call_tool(self, context: Any, call_next: Any) -> Any:
            name = getattr(context.message, "name", "")
            args = getattr(context.message, "arguments", None)
            if not name.startswith("inkscape_") or not isinstance(args, dict):
                return await call_next(context)
            try:
                safe = policy.vet_call(name, args)
            except SecurityError as exc:
                log.warning("blocked %s: %s", name, exc)
                return _denied_result(name, args, f"blocked by security policy: {exc}")
            args.clear()
            args.update(safe)
            return await call_next(context)

    return SecurityMiddleware()
