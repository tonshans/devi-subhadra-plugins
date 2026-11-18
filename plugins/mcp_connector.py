"""Model Context Protocol connector for external tools and IoT sensors."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import Field

from core.base_plugin import BaseAgentPlugin
from core.schemas import PluginOutputSchema, StrictBaseModel


class McpInput(StrictBaseModel):
    action: Literal["list_tools", "call_tool"]
    tool_name: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)


class McpConnector(BaseAgentPlugin):
    plugin_name = "mcp_connector"
    description = "Discover and call tools exposed by an MCP server."
    input_schema = McpInput

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def initialize(self, config: dict) -> bool:
        if config.get("mcp_client") is not None:
            self._client = config["mcp_client"]
        return True

    def execute(self, payload: dict) -> PluginOutputSchema:
        request = McpInput.model_validate(payload)
        if self._client is None:
            return PluginOutputSchema(
                success=False,
                data={},
                error_message="No MCP client configured.",
            )

        try:
            if request.action == "list_tools":
                return PluginOutputSchema(
                    success=True, data={"tools": self._client.list_tools()}
                )
            if not request.tool_name:
                return PluginOutputSchema(
                    success=False,
                    data={},
                    error_message="call_tool requires tool_name.",
                )
            result = self._client.call_tool(request.tool_name, request.arguments)
            return PluginOutputSchema(
                success=True,
                data={"tool_name": request.tool_name, "result": result},
            )
        except Exception as exc:
            return PluginOutputSchema(
                success=False, data={}, error_message=f"MCP call failed: {exc}"
            )

    def shutdown(self) -> None:
        return None