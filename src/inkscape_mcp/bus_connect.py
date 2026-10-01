"""Open a jeepney D-Bus connection that works on Linux, macOS and Windows.

jeepney's own ``open_dbus_connection`` assumes any platform that defines ``socket.SCM_CREDS``
is a BSD that wants credentials passed with the first byte. macOS defines the constant but
rejects the call (``OSError: [Errno 22]``), so *no* bus connection could be opened from
Python on macOS. It also only speaks unix sockets, which rules out the loopback-TCP address
used on Windows. This helper does the same handshake without those assumptions.
"""

from __future__ import annotations

import socket
from urllib.parse import unquote

from jeepney.auth import BEGIN, Authenticator
from jeepney.io.blocking import DBusConnection, unwrap_read


def _parse_address(address: str) -> list[tuple[str, dict[str, str]]]:
    """Split a D-Bus address string into (transport, params) candidates."""
    out: list[tuple[str, dict[str, str]]] = []
    for part in address.split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        transport, _, rest = part.partition(":")
        params: dict[str, str] = {}
        for kv in rest.split(","):
            if "=" in kv:
                k, _, v = kv.partition("=")
                params[k] = unquote(v)
        out.append((transport, params))
    return out


def _connect(address: str, timeout: float) -> socket.socket:
    last: Exception | None = None
    for transport, params in _parse_address(address):
        try:
            if transport == "unix":
                path = params.get("path") or ("\0" + params["abstract"] if "abstract" in params else None)
                if path is None:
                    continue
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                sock.connect(path)
                return sock
            if transport == "tcp":
                return socket.create_connection((params.get("host", "127.0.0.1"), int(params["port"])), timeout)
        except (OSError, KeyError, ValueError) as exc:
            last = exc
    raise ConnectionError(f"could not connect to D-Bus address {address!r}") from last


def open_bus_connection(address: str, timeout: float = 2.0) -> DBusConnection:
    """Connect to ``address`` (e.g. ``unix:path=/tmp/x`` or ``tcp:host=127.0.0.1,port=1234``)."""
    sock = _connect(address, timeout)
    try:
        sock.settimeout(timeout)
        sock.sendall(b"\0")  # plain NUL; no ancillary credentials (see module docstring)
        authr = Authenticator(enable_fds=False, inc_null_byte=False)
        for req in authr:
            sock.sendall(req)
            authr.feed(unwrap_read(sock.recv(1024)))
        sock.sendall(BEGIN)
    except TimeoutError as exc:
        sock.close()
        raise TimeoutError(f"D-Bus authentication timed out after {timeout}s") from exc
    except BaseException:
        sock.close()
        raise
    sock.settimeout(None)
    return DBusConnection(sock, False)
