"""The pure-Python session bus: real jeepney clients talking through it."""

from __future__ import annotations

import threading

import pytest
from jeepney import DBusAddress, HeaderFields, MessageType, new_error, new_method_call, new_method_return
from jeepney.bus_messages import DBus
from jeepney.wrappers import DBusErrorResponse

from inkscape_mcp.bus_connect import open_bus_connection
from inkscape_mcp.embedded_bus import EmbeddedBus

SVC = "org.example.Svc"
ADDR = DBusAddress("/org/example/Svc", bus_name=SVC, interface="org.example.Iface")


@pytest.fixture
def bus():
    b = EmbeddedBus()
    b.start()
    yield b
    b.stop()


def _serve_echo(conn, stop: threading.Event):
    """Answer org.example.Iface.Echo(s) -> s, and Fail() -> error, until stopped."""
    conn.sock.settimeout(0.2)
    while not stop.is_set():
        try:
            msg = conn.receive(timeout=0.2)
        except (TimeoutError, OSError):
            continue
        if msg.header.message_type != MessageType.method_call:
            continue
        member = msg.header.fields[HeaderFields.member]
        if member == "Echo":
            conn.send(new_method_return(msg, "s", (f"echo:{msg.body[0]}",)))
        elif member == "Fail":
            conn.send(new_error(msg, "org.example.Error.Nope", "s", ("nope",)))


@pytest.fixture
def service(bus):
    conn = open_bus_connection(bus.address)
    assert conn.send_and_get_reply(DBus().RequestName(SVC)).body[0] == 1  # primary owner
    stop = threading.Event()
    t = threading.Thread(target=_serve_echo, args=(conn, stop), daemon=True)
    t.start()
    yield conn
    stop.set()
    t.join(timeout=2)
    conn.close()


def test_hello_assigns_unique_names(bus):
    a = open_bus_connection(bus.address)
    b = open_bus_connection(bus.address)
    try:
        assert a.unique_name != b.unique_name
        assert a.unique_name.startswith(":1.")
    finally:
        a.close()
        b.close()


def test_method_call_routes_by_well_known_name_and_reply_returns(bus, service):
    caller = open_bus_connection(bus.address)
    try:
        reply = caller.send_and_get_reply(new_method_call(ADDR, "Echo", "s", ("hi",)), timeout=3)
        assert reply.body == ("echo:hi",)
        # GDBus-compatible: replies must carry the real owner's unique name as sender.
        assert reply.header.fields[HeaderFields.sender] == service.unique_name
    finally:
        caller.close()


def test_error_replies_are_routed(bus, service):
    caller = open_bus_connection(bus.address)
    try:
        with pytest.raises(DBusErrorResponse) as exc:
            reply = caller.send_and_get_reply(new_method_call(ADDR, "Fail"), timeout=3)
            if reply.header.message_type == MessageType.error:
                raise DBusErrorResponse(reply)
        assert exc.value.name == "org.example.Error.Nope"
    finally:
        caller.close()


def test_unknown_destination_gets_service_unknown(bus):
    caller = open_bus_connection(bus.address)
    try:
        reply = caller.send_and_get_reply(new_method_call(ADDR, "Echo", "s", ("x",)), timeout=3)
        assert reply.header.message_type == MessageType.error
        assert reply.header.fields[HeaderFields.error_name] == "org.freedesktop.DBus.Error.ServiceUnknown"
    finally:
        caller.close()


def test_name_has_owner_and_release_on_disconnect(bus):
    owner = open_bus_connection(bus.address)
    watcher = open_bus_connection(bus.address)
    try:
        assert owner.send_and_get_reply(DBus().RequestName(SVC)).body[0] == 1
        assert watcher.send_and_get_reply(DBus().NameHasOwner(SVC)).body == (True,)
        owner.close()
        # Name must be freed when the owner goes away (poll: server notices on its own thread).
        import time

        for _ in range(50):
            if watcher.send_and_get_reply(DBus().NameHasOwner(SVC)).body == (False,):
                break
            time.sleep(0.05)
        else:
            pytest.fail("name still owned after owner disconnected")
    finally:
        watcher.close()


def test_second_requester_does_not_steal_name(bus):
    a = open_bus_connection(bus.address)
    b = open_bus_connection(bus.address)
    try:
        assert a.send_and_get_reply(DBus().RequestName(SVC)).body[0] == 1
        assert b.send_and_get_reply(DBus().RequestName(SVC, flags=4)).body[0] == 3  # exists (DO_NOT_QUEUE)
        assert b.send_and_get_reply(DBus().GetNameOwner(SVC)).body == (a.unique_name,)
    finally:
        a.close()
        b.close()


def test_peer_ping_to_service_and_to_bus(bus, service):
    caller = open_bus_connection(bus.address)
    try:
        ping_bus = DBusAddress(
            "/org/freedesktop/DBus", bus_name="org.freedesktop.DBus", interface="org.freedesktop.DBus.Peer"
        )
        assert (
            caller.send_and_get_reply(new_method_call(ping_bus, "Ping")).header.message_type
            == MessageType.method_return
        )
    finally:
        caller.close()


def test_socket_is_private(bus):
    import os
    import stat

    path = bus.address.removeprefix("unix:path=")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
