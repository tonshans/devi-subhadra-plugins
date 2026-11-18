import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "devi-plugins.py"
_spec = importlib.util.spec_from_file_location("devi_plugins", MODULE_PATH)
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)

GOOD_PLUGIN = """
from core.base_plugin import BaseAgentPlugin
from core.schemas import StrictBaseModel


class DemoInput(StrictBaseModel):
    task: str


class DemoPlugin(BaseAgentPlugin):
    plugin_name = "demo"
    description = "Demo plugin."
    input_schema = DemoInput

    def initialize(self, config):
        return True

    def execute(self, payload):
        return None

    def shutdown(self):
        return None
"""


def _quiet(function, *args, **kwargs):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        function(*args, **kwargs)
    return buffer.getvalue()


class InspectTests(unittest.TestCase):
    def _inspect(self, source: str) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.py"
            path.write_text(source, encoding="utf-8")
            return dp.inspect_plugin(path)

    def test_accepts_valid_plugin(self):
        self.assertEqual(self._inspect(GOOD_PLUGIN), ("demo", "Demo plugin."))

    def test_rejects_missing_lifecycle_method(self):
        broken = GOOD_PLUGIN.replace("    def shutdown(self):\n        return None\n", "")
        with self.assertRaises(dp.PluginError):
            self._inspect(broken)

    def test_rejects_forbidden_core_import(self):
        broken = GOOD_PLUGIN.replace(
            "from core.schemas import StrictBaseModel",
            "from core.cognitive_ledger import CognitiveLedger\n"
            "from core.schemas import StrictBaseModel",
        )
        with self.assertRaises(dp.PluginError):
            self._inspect(broken)

    def test_rejects_filename_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "other.py"
            path.write_text(GOOD_PLUGIN, encoding="utf-8")
            with self.assertRaises(dp.PluginError):
                dp.inspect_plugin(path)


class ConfigTests(unittest.TestCase):
    def test_flat_config_ignores_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                "# comment\nagent_dir: ../agent  # inline\n\nother: 'x'\n",
                encoding="utf-8",
            )
            values = dp.read_config(path)
        self.assertEqual(values["agent_dir"], "../agent")
        self.assertEqual(values["other"], "x")


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.agent = root / "agent"
        (self.agent / "core").mkdir(parents=True)
        (self.agent / "plugins").mkdir()
        (self.agent / "tests").mkdir()
        self.catalog = root / "catalog"
        self.catalog.mkdir()
        (self.catalog / "demo.py").write_text(GOOD_PLUGIN, encoding="utf-8")
        (self.catalog / "demo.test.py").write_text("# test\n", encoding="utf-8")
        self._old_catalog = dp.CATALOG
        dp.CATALOG = self.catalog

    def tearDown(self):
        dp.CATALOG = self._old_catalog
        self.tmp.cleanup()

    def test_install_copies_plugin_and_test(self):
        _quiet(dp.command_install, self.agent, "demo")
        self.assertTrue((self.agent / "plugins" / "demo.py").is_file())
        self.assertTrue((self.agent / "tests" / "demo.test.py").is_file())

    def test_remove_deletes_installed_plugin(self):
        _quiet(dp.command_install, self.agent, "demo")
        _quiet(dp.command_remove, self.agent, "demo", False)
        self.assertFalse((self.agent / "plugins" / "demo.py").exists())
        self.assertFalse((self.agent / "tests" / "demo.test.py").exists())

    def test_remove_refuses_local_plugin_without_force(self):
        local = self.agent / "plugins" / "handmade.py"
        local.write_text("# local\n", encoding="utf-8")
        with self.assertRaises(dp.PluginError):
            dp.command_remove(self.agent, "handmade", False)
        _quiet(dp.command_remove, self.agent, "handmade", True)
        self.assertFalse(local.exists())

    def test_install_rejects_unknown_plugin(self):
        with self.assertRaises(dp.PluginError):
            dp.command_install(self.agent, "missing")


if __name__ == "__main__":
    unittest.main()
