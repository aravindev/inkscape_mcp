"""A minimal, pure-Python D-Bus session bus for the live Inkscape bridge.

Why this exists: controlling a *running* Inkscape window goes through its ``org.gtk.Actions``
D-Bus interface, which needs a message bus to route calls. Linux desktops have one; macOS
and Windows do not, and the previous workaround (a real ``dbus-daemon``, from MSYS2 on
Windows, Homebrew on macOS) is a heavy extra install. This module is just enough of a bus
to let one Inkscape GUI and this server talk to each other, on any OS, with zero extra
dependencies beyond ``jeepney`` (already required).

Scope, deliberately small:
  * unix-socket transport (Linux/macOS) or loopback TCP (Windows); EXTERNAL and ANONYMOUS auth
  * the ``org.freedesktop.DBus`` methods GDBus/GApplication/jeepney actually call
  * method-call / reply / error routing with correct ``sender`` stamping (GDBus drops
    replies whose sender does not match the destination's owner)
  * signals: delivered to their destination, or broadcast when they have none

It is NOT a general-purpose bus: no activation, no policy, no match-rule filtering (all
broadcast signals go to every other peer), no file-descriptor passing. It binds to loopback
or a private 0700 socket only, and is meant to be driven by one local user.
"""

from __future__ import annotations

import logging
import os
import secrets
import socket
import tempfile
import threading
from pathlib import Path
from typing import Any

from jeepney import HeaderFields, Message, MessageType, new_error, new_method_return
from jeepney.low_level import Parser
from jeepney.wrappers import DBusAddress, new_signal

log = logging.getLogger(__name__)

BUS_NAME = "org.freedesktop.DBus"
BUS_PATH = "/org/freedesktop/DBus"

# RequestName reply codes / flags (D-Bus spec).
_PRIMARY_OWNER, _IN_QUEUE, _EXISTS, _ALREADY_OWNER = 1, 2, 3, 4
_FLAG_DO_NOT_QUEUE = 0x4
_FLAG_NO_REPLY_EXPECTED = 0x1

_INTROSPECT_XML = (
    '<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN" '
    '"http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">'
    '<node><interface name="org.freedesktop.DBus"/></node>'
)


class _Peer:
    """One connected client."""

    def __init__(self, sock: socket.socket, unique_name: str) -> None:
        self.sock = sock
        self.unique_name = unique_name
        self.said_hello = False
        self._send_lock = threading.Lock()

    def send(self, msg: Message, serial: int | None = None) -> None:
        data = msg.serialise(serial=serial if serial is not None else msg.header.serial)
        try:
            with self._send_lock:
                self.sock.sendall(data)
        except OSError:
            log.debug("send to %s failed (peer gone)", self.unique_name)


class EmbeddedBus:
    """Run with :meth:`start`; clients connect to the returned address string."""

    def __init__(self, tcp: bool = False) -> None:
        self._tcp = tcp
        self._server: socket.socket | None = None
        self._sock_dir: Path | None = None
        self._guid = secrets.token_hex(16)
        self._lock = threading.RLock()
        self._peers: dict[str, _Peer] = {}  # unique name -> peer
        self._owners: dict[str, str] = {}  # well-known name -> unique name
        self._next_id = 1
        self._serial = 0
        self._stop = threading.Event()
        self.address = ""

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> str:
        if self._tcp:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", 0))
            self.address = f"tcp:host=127.0.0.1,port={srv.getsockname()[1]}"
        else:
            # 0700 temp dir => only this user can reach the socket (that *is* our auth boundary).
            self._sock_dir = Path(tempfile.mkdtemp(prefix="inkmcp-bus-"))
            os.chmod(self._sock_dir, 0o700)
            path = self._sock_dir / "bus"
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(path))
            os.chmod(path, 0o600)
            self.address = f"unix:path={path}"
        srv.listen(16)
        self._server = srv
        threading.Thread(target=self._accept_loop, name="embedded-bus-accept", daemon=True).start()
        log.info("embedded D-Bus listening on %s", self.address)
        return self.address

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        with self._lock:
            peers = list(self._peers.values())
        for p in peers:
            try:
                p.sock.close()
            except OSError:
                pass
        if self._sock_dir is not None:
            for f in self._sock_dir.glob("*"):
                f.unlink(missing_ok=True)
            try:
                self._sock_dir.rmdir()
            except OSError:
                pass

    # ------------------------------------------------------------------ connections
    def _accept_loop(self) -> None:
        server = self._server
        if server is None:
            return
        while not self._stop.is_set():
            try:
                sock, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock,), name="embedded-bus-peer", daemon=True).start()

    def _serve(self, sock: socket.socket) -> None:
        with self._lock:
            unique = f":1.{self._next_id}"
            self._next_id += 1
        peer = _Peer(sock, unique)
        try:
            leftover = self._authenticate(sock)
            if leftover is None:
                return
            with self._lock:
                self._peers[unique] = peer
            parser = Parser()
            if leftover:
                parser.add_data(leftover)
            self._pump(peer, parser)
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                parser.add_data(data)
                self._pump(peer, parser)
        except (OSError, ValueError) as exc:
            log.debug("peer %s ended: %s", unique, exc)
        finally:
            self._drop(peer)

    def _authenticate(self, sock: socket.socket) -> bytes | None:
        """SASL handshake. Returns bytes received after BEGIN, or None on failure."""
        buf = b""
        first = True
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                return None
            buf += chunk
            if first and buf:
                buf = buf[1:] if buf[:1] == b"\0" else buf  # leading credentials byte
                first = False
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                cmd, _, rest = line.decode("ascii", "replace").partition(" ")
                cmd = cmd.upper()
                if cmd == "AUTH":
                    mech = rest.split(" ", 1)[0].upper()
                    if mech in ("EXTERNAL", "ANONYMOUS"):
                        sock.sendall(f"OK {self._guid}\r\n".encode())
                    else:
                        sock.sendall(b"REJECTED EXTERNAL ANONYMOUS\r\n")
                elif cmd == "NEGOTIATE_UNIX_FD":
                    sock.sendall(b'ERROR "fd passing unsupported"\r\n')
                elif cmd == "BEGIN":
                    return buf
                elif cmd == "CANCEL":
                    sock.sendall(b"REJECTED EXTERNAL ANONYMOUS\r\n")
                elif cmd == "DATA":
                    sock.sendall(b"DATA\r\n")
                else:
                    sock.sendall(b"ERROR\r\n")

    def _drop(self, peer: _Peer) -> None:
        with self._lock:
            self._peers.pop(peer.unique_name, None)
            lost = [n for n, o in self._owners.items() if o == peer.unique_name]
            for n in lost:
                del self._owners[n]
        try:
            peer.sock.close()
        except OSError:
            pass
        for n in lost:
            self._broadcast(self._signal("NameOwnerChanged", "sss", (n, peer.unique_name, "")))

    # ------------------------------------------------------------------ routing
    def _pump(self, peer: _Peer, parser: Parser) -> None:
        while True:
            msg = parser.get_next_message()
            if msg is None:
                return
            self._route(peer, msg)

    def _route(self, peer: _Peer, msg: Message) -> None:
        fields = msg.header.fields
        dest = fields.get(HeaderFields.destination)
        mtype = msg.header.message_type

        if not peer.said_hello and not (
            mtype == MessageType.method_call and fields.get(HeaderFields.member) == "Hello" and dest == BUS_NAME
        ):
            return  # protocol violation: must Hello first

        if dest == BUS_NAME:
            if mtype == MessageType.method_call:
                self._bus_call(peer, msg)
            return

        # Stamp the sender; the bus is the only party allowed to set it.
        fields[HeaderFields.sender] = peer.unique_name

        if mtype == MessageType.signal and dest is None:
            self._broadcast(msg, skip=peer)
            return

        target = self._resolve(dest) if dest else None
        if target is None:
            if mtype == MessageType.method_call and not (msg.header.flags & _FLAG_NO_REPLY_EXPECTED):
                self._reply_error(
                    peer,
                    msg,
                    "org.freedesktop.DBus.Error.ServiceUnknown",
                    f"The name {dest} was not provided by any .service files",
                )
            return
        target.send(msg)

    def _resolve(self, name: str) -> _Peer | None:
        with self._lock:
            unique = name if name.startswith(":") else self._owners.get(name)
            return self._peers.get(unique) if unique else None

    def _broadcast(self, msg: Message, skip: _Peer | None = None) -> None:
        with self._lock:
            peers = [p for p in self._peers.values() if p is not skip and p.said_hello]
        for p in peers:
            p.send(msg)

    def _next_serial(self) -> int:
        with self._lock:
            self._serial += 1
            return self._serial

    def _signal(self, member: str, sig: str, body: tuple[Any, ...], dest: str | None = None) -> Message:
        addr = DBusAddress(BUS_PATH, bus_name=dest, interface=BUS_NAME)
        m = new_signal(addr, member, sig, body)
        m.header.fields[HeaderFields.sender] = BUS_NAME
        m.header.serial = self._next_serial()
        return m

    def _reply(self, peer: _Peer, call: Message, sig: str = "", body: tuple[Any, ...] = ()) -> None:
        if call.header.flags & _FLAG_NO_REPLY_EXPECTED:
            return
        r = new_method_return(call, sig, body)
        r.header.fields[HeaderFields.sender] = BUS_NAME
        peer.send(r, serial=self._next_serial())

    def _reply_error(self, peer: _Peer, call: Message, name: str, text: str) -> None:
        e = new_error(call, name, "s", (text,))
        e.header.fields[HeaderFields.sender] = BUS_NAME
        peer.send(e, serial=self._next_serial())

    # ------------------------------------------------------------------ org.freedesktop.DBus
    def _bus_call(self, peer: _Peer, msg: Message) -> None:
        member = msg.header.fields.get(HeaderFields.member)
        iface = msg.header.fields.get(HeaderFields.interface)
        body = msg.body

        if iface == "org.freedesktop.DBus.Peer":
            if member == "Ping":
                self._reply(peer, msg)
            elif member == "GetMachineId":
                self._reply(peer, msg, "s", (self._guid,))
            return
        if iface == "org.freedesktop.DBus.Introspectable" and member == "Introspect":
            self._reply(peer, msg, "s", (_INTROSPECT_XML,))
            return

        if member == "Hello":
            if peer.said_hello:
                self._reply_error(peer, msg, "org.freedesktop.DBus.Error.Failed", "Already handled Hello")
                return
            peer.said_hello = True
            self._reply(peer, msg, "s", (peer.unique_name,))
            peer.send(self._signal("NameAcquired", "s", (peer.unique_name,), dest=peer.unique_name))
            self._broadcast(
                self._signal("NameOwnerChanged", "sss", (peer.unique_name, "", peer.unique_name)), skip=peer
            )
        elif member == "RequestName":
            name, flags = body
            self._request_name(peer, msg, name, flags)
        elif member == "ReleaseName":
            (name,) = body
            with self._lock:
                owned = self._owners.get(name) == peer.unique_name
                if owned:
                    del self._owners[name]
            self._reply(peer, msg, "u", (1 if owned else 2,))  # 1 released, 2 non-existent/not owner
            if owned:
                self._broadcast(self._signal("NameOwnerChanged", "sss", (name, peer.unique_name, "")))
        elif member == "NameHasOwner":
            (name,) = body
            self._reply(peer, msg, "b", (self._resolve(name) is not None,))
        elif member == "GetNameOwner":
            (name,) = body
            target = self._resolve(name)
            if target is None:
                self._reply_error(
                    peer, msg, "org.freedesktop.DBus.Error.NameHasNoOwner", f"Could not get owner of name '{name}'"
                )
            else:
                self._reply(peer, msg, "s", (target.unique_name,))
        elif member == "ListNames":
            with self._lock:
                names = [BUS_NAME, *self._owners, *self._peers]
            self._reply(peer, msg, "as", (names,))
        elif member == "ListActivatableNames":
            self._reply(peer, msg, "as", ([],))
        elif member == "ListQueuedOwners":
            (name,) = body
            target = self._resolve(name)
            self._reply(peer, msg, "as", ([target.unique_name] if target else [],))
        elif member in ("AddMatch", "RemoveMatch", "UpdateActivationEnvironment", "ReloadConfig"):
            self._reply(peer, msg)
        elif member == "GetId":
            self._reply(peer, msg, "s", (self._guid,))
        elif member == "GetConnectionUnixUser":
            self._reply(peer, msg, "u", (os.getuid() if hasattr(os, "getuid") else 0,))
        elif member == "GetConnectionUnixProcessID":
            self._reply_error(peer, msg, "org.freedesktop.DBus.Error.UnknownMethod", "pid not tracked")
        elif member == "StartServiceByName":
            self._reply_error(peer, msg, "org.freedesktop.DBus.Error.ServiceUnknown", "activation unsupported")
        else:
            self._reply_error(peer, msg, "org.freedesktop.DBus.Error.UnknownMethod", f"Unknown method {member}")

    def _request_name(self, peer: _Peer, msg: Message, name: str, flags: int) -> None:
        if name.startswith(":") or name == BUS_NAME:
            self._reply_error(peer, msg, "org.freedesktop.DBus.Error.InvalidArgs", f"Name not requestable: {name}")
            return
        with self._lock:
            current = self._owners.get(name)
            if current is None:
                self._owners[name] = peer.unique_name
                code = _PRIMARY_OWNER
            elif current == peer.unique_name:
                code = _ALREADY_OWNER
            else:
                code = _EXISTS if flags & _FLAG_DO_NOT_QUEUE else _IN_QUEUE
        self._reply(peer, msg, "u", (code,))
        if code == _PRIMARY_OWNER:
            peer.send(self._signal("NameAcquired", "s", (name,), dest=peer.unique_name))
            self._broadcast(self._signal("NameOwnerChanged", "sss", (name, "", peer.unique_name)))
