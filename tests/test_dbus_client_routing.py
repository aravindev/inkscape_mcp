"""Jeepney routing regressions with no real session bus or Inkscape process."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jeepney import HeaderFields, MessageType

from inkscape_mcp import dbus_client

APP_PATH = "/org/inkscape/Inkscape"
WINDOW_PATH = f"{APP_PATH}/window"
DOCUMENT_PATH = f"{APP_PATH}/document"


@pytest.fixture
def mock_bus(monkeypatch):
    calls = []

    def reply_to(message):
        fields = message.header.fields
        path = fields[HeaderFields.path]
        member = fields[HeaderFields.member]
        calls.append((path, member, message.body))
        if member == "Introspect":
            xml = {
                APP_PATH: '<node><node name="document"/><node name="window"/></node>',
                WINDOW_PATH: '<node><node name="7"/><node name="2"/><node name="ignored"/></node>',
                DOCUMENT_PATH: '<node><node name="99"/></node>',
            }[path]
            body = (xml,)
        elif member == "List":
            body = (["paste", "paste-in-place"],)
        elif member == "Describe":
            body = ((True, "", []),)
        elif member == "Activate":
            body = ()
        else:
            raise AssertionError(f"Unexpected D-Bus method: {member}")
        return SimpleNamespace(header=SimpleNamespace(message_type=MessageType.method_return), body=body)

    connection = Mock()
    connection.send_and_get_reply.side_effect = reply_to
    monkeypatch.setattr(dbus_client, "open_dbus_connection", Mock(return_value=connection))
    return dbus_client.InkscapeDBus(), calls


def test_list_windows_ignores_coexisting_documents(mock_bus):
    bus, calls = mock_bus

    assert bus.list_windows() == [2, 7]
    assert calls == [(WINDOW_PATH, "Introspect", ())]


@pytest.mark.parametrize("scope", ["app", "window"])
@pytest.mark.parametrize("operation", ["list_actions", "describe", "activate"])
def test_action_routes_ignore_coexisting_documents(mock_bus, scope, operation):
    bus, calls = mock_bus
    expected_path = APP_PATH if scope == "app" else f"{WINDOW_PATH}/7"

    if operation == "list_actions":
        assert bus.list_actions(scope=scope, window_id=7) == ["paste", "paste-in-place"]
        assert calls == [(expected_path, "List", ())]
    elif operation == "describe":
        assert bus.describe("paste", scope=scope, window_id=7) == (True, "", [])
        assert calls == [(expected_path, "Describe", ("paste",))]
    else:
        bus.activate("paste", scope=scope, window_id=7)
        assert calls == [
            (expected_path, "Describe", ("paste",)),
            (expected_path, "Activate", ("paste", [], {})),
        ]
