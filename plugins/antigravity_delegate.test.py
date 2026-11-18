"""Unit tests for the agy delegation plugin; the real CLI is never executed."""

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from plugins.antigravity_delegate import (
    _SELF_TOOLING_OVERRIDE,
    AntigravityDelegate,
    AntigravityPayload,
)


class _FakeProcess:
    def __init__(
        self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.pid = 4242
        self.wait = AsyncMock(return_value=returncode)

    async def communicate(self) -> tuple[bytes, bytes]:
        return self.stdout, self.stderr


class AntigravityDelegateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = AntigravityDelegate()
        assert self.plugin.initialize(
            {
                "paths": {
                    "workspace_dir": "/mnt/workspace",
                    "atelier_dir": "/mnt/agent_atelier",
                }
            }
        )

    @staticmethod
    def _payload(**overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action_type": "edit_project",
            "instruction": "build",
            "target_directory": "demo",
        }
        payload.update(overrides)
        return payload

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    def test_subprocess_runs_as_agent(self, create: AsyncMock) -> None:
        create.return_value = _FakeProcess(stdout=b"ok")

        result = self.plugin.execute(self._payload(additional_args=["--yes"]))

        assert result.success is True
        args, kwargs = create.call_args
        assert args == ("sudo", "-H", "-u", "agent", "agy", "build", "--yes")
        assert kwargs["cwd"] == "/mnt/workspace/demo"
        assert "shell" not in kwargs

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    def test_new_project_appends_self_tooling_override(
        self, create: AsyncMock
    ) -> None:
        create.return_value = _FakeProcess(stdout=b"project created")

        result = self.plugin.execute(self._payload(action_type="new_project"))

        assert result.success is True
        assert result.data["stdout"] == "project created" + _SELF_TOOLING_OVERRIDE
        assert "[SYSTEM OVERRIDE - MANDATORY ACTION]" in result.data["stdout"]
        assert result.data["stdout"].endswith("=" * 40)

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    def test_other_actions_do_not_inject_override(self, create: AsyncMock) -> None:
        create.return_value = _FakeProcess(stdout=b"done")

        result = self.plugin.execute(self._payload(action_type="edit_project"))

        assert result.data["stdout"] == "done"
        assert "SYSTEM OVERRIDE" not in result.data["stdout"]

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaises(ValidationError):
            AntigravityPayload.model_validate(
                self._payload(target_directory="../../etc/")
            )

    def test_rejects_absolute_path_outside_roots(self) -> None:
        with self.assertRaises(ValidationError):
            AntigravityPayload.model_validate(
                self._payload(target_directory="/etc/passwd")
            )

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    def test_allows_absolute_path_inside_atelier(self, create: AsyncMock) -> None:
        create.return_value = _FakeProcess(stdout=b"ok")

        result = self.plugin.execute(
            self._payload(target_directory="/mnt/agent_atelier/demo")
        )

        assert result.success is True
        assert create.call_args.kwargs["cwd"] == "/mnt/agent_atelier/demo"

    @patch("os.killpg")
    @patch("asyncio.wait_for", new_callable=AsyncMock)
    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    def test_timeout_kills_process_and_reports_hint(
        self, create: AsyncMock, wait_for: AsyncMock, killpg: Any
    ) -> None:
        process = _FakeProcess()
        create.return_value = process

        async def _raise_timeout(coro: Any, timeout: int) -> None:
            coro.close()
            raise asyncio.TimeoutError

        wait_for.side_effect = _raise_timeout

        result = self.plugin.execute(self._payload(timeout_seconds=1))

        assert result.success is False
        assert "non-interaktif" in result.error_message
        assert wait_for.call_args.kwargs["timeout"] == 1
        killpg.assert_called_once()
        process.wait.assert_awaited_once()

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    def test_exit_code_1_returns_clear_error(self, create: AsyncMock) -> None:
        create.return_value = _FakeProcess(
            stdout=b"partial", stderr=b"boom", returncode=1
        )

        result = self.plugin.execute(self._payload())

        assert result.success is False
        assert "code 1" in result.error_message
        assert "boom" in result.error_message
        assert result.data["stderr"] == "boom"
        assert result.data["returncode"] == 1

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    def test_missing_binary_is_reported(self, create: AsyncMock) -> None:
        create.side_effect = FileNotFoundError("sudo")

        result = self.plugin.execute(self._payload())

        assert result.success is False
        assert "Failed to start agy" in result.error_message
