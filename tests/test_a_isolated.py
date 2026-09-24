import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_config_a_and_shared_code_do_not_import_agentguard():
    files = [ROOT / "config_a.py", *ROOT.glob("agent/**/*.py"), *ROOT.glob("tools/**/*.py")]
    offenders = [str(f.relative_to(ROOT)) for f in files if "agentguard" in _imports(f)]
    assert offenders == []
