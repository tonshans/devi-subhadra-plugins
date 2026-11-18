#!/usr/bin/env python3
"""Install/remove devi-subhadra plugins from this catalog into an agent checkout.

Usage:
    python3 devi-plugins.py [--dir=<agent>] available
    python3 devi-plugins.py [--dir=<agent>] installed
    python3 devi-plugins.py [--dir=<agent>] install <plugin>
    python3 devi-plugins.py [--dir=<agent>] remove <plugin> [--force]
    python3 devi-plugins.py [--dir=<agent>] verify <plugin>

Only the standard library is used, so the script runs with system python3.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "plugins"
CONFIG = ROOT / "config.yaml"
DEFAULT_AGENT = ROOT.parent / "devi-subhadra"

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ALLOWED_CORE_IMPORTS = {"core.base_plugin", "core.schemas", "core.config_loader"}
LIFECYCLE_METHODS = {"initialize", "execute", "shutdown"}


class PluginError(Exception):
    """A plugin cannot be inspected or installed."""


class PluginInfo(NamedTuple):
    name: str
    description: str
    notes: list[str]


def read_config(path: Path = CONFIG) -> dict[str, str]:
    """Flat `key: value` YAML subset; comments and blank lines are ignored."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def resolve_agent(cli_dir: str | None) -> Path:
    if cli_dir:
        return Path(cli_dir).expanduser().resolve()
    configured = read_config().get("agent_dir")
    if configured:
        return (ROOT / configured).expanduser().resolve()
    return DEFAULT_AGENT


def _module_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                constants[target.id] = node.value.value
    return constants


def _class_attr(
    cls: ast.ClassDef, name: str, constants: dict[str, str]
) -> str | None:
    for node in cls.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        else:
            continue
        if name not in targets:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        if isinstance(value, ast.Name):
            return constants.get(value.id)
    return None


def _is_base_plugin(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "BaseAgentPlugin":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseAgentPlugin":
            return True
    return False


def _install_notes(tree: ast.Module) -> list[str]:
    """Module docstring: first line is a summary, the rest are post-install steps."""
    docstring = ast.get_docstring(tree) or ""
    return [line.strip() for line in docstring.splitlines()[1:] if line.strip()]


def inspect_plugin(path: Path) -> PluginInfo:
    """Static contract check: no import needed, so missing deps cannot hide errors."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise PluginError(f"syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "core" and node.module not in ALLOWED_CORE_IMPORTS:
                raise PluginError(
                    f"imports forbidden module '{node.module}'; plugins may import only "
                    + ", ".join(sorted(ALLOWED_CORE_IMPORTS))
                )

    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and _is_base_plugin(node)
    ]
    if len(classes) != 1:
        raise PluginError("expected exactly one BaseAgentPlugin subclass")

    cls = classes[0]
    constants = _module_constants(tree)
    name = _class_attr(cls, "plugin_name", constants)
    description = _class_attr(cls, "description", constants)

    if not name or not NAME_RE.fullmatch(name):
        raise PluginError("plugin_name must be a lowercase snake_case string")
    if path.stem != name:
        raise PluginError(f"filename '{path.stem}' does not match plugin_name '{name}'")
    if not description:
        raise PluginError("description must be a literal string")

    assigned = {
        target.id
        for node in cls.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
    }
    if "input_schema" not in assigned:
        raise PluginError("input_schema must be set on the plugin class")

    methods = {
        node.name
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = LIFECYCLE_METHODS - methods
    if missing:
        raise PluginError("missing lifecycle methods: " + ", ".join(sorted(missing)))

    return PluginInfo(name, description, _install_notes(tree))


def catalog_plugins() -> list[Path]:
    if not CATALOG.is_dir():
        return []
    return sorted(
        path
        for path in CATALOG.glob("*.py")
        if not path.name.startswith("_") and not path.name.endswith(".test.py")
    )


def _agent_python(agent: Path) -> Path | None:
    venv_python = agent / ".venv" / "bin" / "python"
    return venv_python if venv_python.is_file() else None


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=180
    )


def _dependency_hint(output: str) -> str:
    match = re.search(r"No module named '([^']+)'", output)
    if not match:
        return ""
    module = match.group(1).split(".")[0]
    if module == "playwright":
        return (
            "\nhint: plugin needs a browser extra: "
            f"cd {ROOT.parent / 'devi-subhadra'} && uv sync --extra browser"
        )
    return f"\nhint: install the missing dependency in the agent venv: uv pip install {module}"


def verify_load(agent: Path, name: str) -> None:
    python = _agent_python(agent)
    if python is None:
        print("warning: no agent .venv found, skipping runtime load check")
        return
    code = (
        "import sys\n"
        "from core.plugin_loader import PluginLoader\n"
        "loader = PluginLoader(sys.argv[1])\n"
        "plugin = loader.load_plugin(sys.argv[2])\n"
        "if plugin is None:\n"
        "    print(loader.errors or 'plugin not loadable')\n"
        "    sys.exit(1)\n"
    )
    result = _run([str(python), "-c", code, str(agent / "plugins"), name], agent)
    if result.returncode:
        output = (result.stdout + result.stderr).strip()
        raise PluginError(
            f"agent cannot load plugin:\n{output}{_dependency_hint(output)}"
        )


def command_available(agent: Path) -> None:
    print(f"catalog: {CATALOG}")
    print(f"agent:   {agent}")
    if not catalog_plugins():
        print("no plugins in catalog")
        return
    for path in catalog_plugins():
        try:
            info = inspect_plugin(path)
        except PluginError as exc:
            print(f"  INVALID  {path.name}: {exc}")
            continue
        mark = "*" if (agent / "plugins" / f"{info.name}.py").is_file() else " "
        summary = " ".join(info.description.split())
        if len(summary) > 78:
            summary = summary[:75] + "..."
        print(f" [{mark}] {info.name:<24} {summary}")


def command_installed(agent: Path) -> None:
    plugins_dir = agent / "plugins"
    if not plugins_dir.is_dir():
        raise PluginError(f"not an agent checkout: {plugins_dir} is missing")
    names = sorted(
        path.stem
        for path in plugins_dir.glob("*.py")
        if not path.name.startswith("_") and not path.name.endswith(".test.py")
    )
    if not names:
        print(f"no plugins installed in {plugins_dir}")
        return
    for name in names:
        origin = "catalog" if (CATALOG / f"{name}.py").is_file() else "local"
        print(f"  {name:<24} [{origin}]")


def command_install(agent: Path, name: str) -> None:
    source = CATALOG / f"{name}.py"
    if not source.is_file():
        raise PluginError(f"'{name}' is not in the catalog ({CATALOG})")
    if not (agent / "core").is_dir():
        raise PluginError(f"{agent} does not look like a devi-subhadra checkout")

    info = inspect_plugin(source)
    if info.name != name:
        raise PluginError(f"catalog file plugin_name is '{info.name}', not '{name}'")

    target_dir = agent / "plugins"
    tests_dir = agent / "tests"
    target_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / source.name
    source_test = CATALOG / f"{name}.test.py"
    target_test = tests_dir / source_test.name
    already = target.is_file()

    shutil.copy2(source, target)
    if source_test.is_file():
        shutil.copy2(source_test, target_test)

    try:
        verify_load(agent, name)
    except Exception:
        target.unlink(missing_ok=True)
        target_test.unlink(missing_ok=True)
        raise

    print(f"{'updated' if already else 'installed'}: {target}")
    if source_test.is_file():
        print(f"installed test: {target_test}")
    if info.notes:
        print("next steps:")
        for note in info.notes:
            print(f"  - {note}")


def command_remove(agent: Path, name: str, force: bool) -> None:
    target = agent / "plugins" / f"{name}.py"
    if not target.is_file():
        raise PluginError(f"'{name}' is not installed in {agent / 'plugins'}")
    if not (CATALOG / f"{name}.py").is_file() and not force:
        raise PluginError(
            f"'{name}' is not from this catalog (agent-created?). "
            "Re-run with --force if you really want to delete it."
        )
    target.unlink()
    (agent / "tests" / f"{name}.test.py").unlink(missing_ok=True)
    print(f"removed: {target}")


def command_verify(agent: Path, name: str) -> None:
    if not (agent / "plugins" / f"{name}.py").is_file():
        raise PluginError(f"'{name}' is not installed in {agent / 'plugins'}")
    verify_load(agent, name)
    test = agent / "tests" / f"{name}.test.py"
    if not test.is_file():
        print(f"load ok: {name} (no test installed)")
        return
    python = _agent_python(agent)
    if python is None:
        raise PluginError("no agent .venv found; cannot run pytest")
    result = _run([str(python), "-m", "pytest", str(test)], agent)
    if result.returncode:
        raise PluginError(f"plugin test failed:\n{result.stdout}{result.stderr}".strip())
    print(f"ok: {name} (load + test)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devi-plugins.py",
        description="Install or remove devi-subhadra plugins.",
    )
    parser.add_argument(
        "--dir",
        help="path to the devi-subhadra checkout (default: config.yaml agent_dir)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        child = sub.add_parser(name, help=help_text)
        # Duplicated so --dir works before or after the command name.
        child.add_argument("--dir", default=argparse.SUPPRESS)
        return child

    add("help", "show this help")
    add("available", "list plugins ready to install")
    add("installed", "list plugins already installed in the agent")
    install = add("install", "install one plugin")
    install.add_argument("plugin")
    remove = add("remove", "remove one installed plugin")
    remove.add_argument("plugin")
    remove.add_argument("--force", action="store_true")
    verify = add("verify", "load one installed plugin and run its test")
    verify.add_argument("plugin")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "help":
        parser.print_help()
        return 0

    agent = resolve_agent(args.dir)
    try:
        if args.command == "available":
            command_available(agent)
        elif args.command == "installed":
            command_installed(agent)
        elif args.command == "install":
            command_install(agent, args.plugin)
        elif args.command == "remove":
            command_remove(agent, args.plugin, args.force)
        elif args.command == "verify":
            command_verify(agent, args.plugin)
    except PluginError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
