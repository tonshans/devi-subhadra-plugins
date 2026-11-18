"""Unit tests for MCP tool discovery and invocation."""

from plugins.mcp_connector import McpConnector


class FakeClient:
    def __init__(self):
        self.calls = []

    def list_tools(self):
        return [
            {
                "name": "sensor_read",
                "description": "Read a sensor value.",
                "inputSchema": {"type": "object"},
            }
        ]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"value": 21.5}


class BrokenClient:
    def list_tools(self):
        raise RuntimeError("server offline")

    def call_tool(self, name, arguments):
        raise RuntimeError("server offline")


def test_lists_tools_from_connected_server():
    client = FakeClient()
    plugin = McpConnector(client=client)
    assert plugin.initialize({}) is True

    result = plugin.execute({"action": "list_tools"})

    assert result.success is True
    assert result.data["tools"][0]["name"] == "sensor_read"


def test_calls_tool_with_arguments():
    client = FakeClient()
    plugin = McpConnector(client=client)
    plugin.initialize({})

    result = plugin.execute(
        {
            "action": "call_tool",
            "tool_name": "sensor_read",
            "arguments": {"sensor_id": "temp-1"},
        }
    )

    assert result.success is True
    assert result.data["tool_name"] == "sensor_read"
    assert result.data["result"] == {"value": 21.5}
    assert client.calls == [("sensor_read", {"sensor_id": "temp-1"})]


def test_call_tool_requires_tool_name():
    client = FakeClient()
    plugin = McpConnector(client=client)
    plugin.initialize({})

    result = plugin.execute({"action": "call_tool", "arguments": {}})

    assert result.success is False
    assert "tool_name" in result.error_message
    assert client.calls == []


def test_reports_server_failure_without_raising():
    plugin = McpConnector(client=BrokenClient())
    plugin.initialize({})

    result = plugin.execute({"action": "list_tools"})

    assert result.success is False
    assert "server offline" in result.error_message