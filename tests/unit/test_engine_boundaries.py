import ast
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[2] / "app" / "engine"

FORBIDDEN_IMPORTS = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "psycopg",
    "torch",
    "app.db",
    "app.modules",
    "app.core",
)


def is_forbidden_import(module_name: str) -> bool:
    """Check whether a module violates engine dependencies."""
    return any(
        module_name == forbidden or module_name.startswith(f"{forbidden}.")
        for forbidden in FORBIDDEN_IMPORTS
    )


def find_forbidden_imports(source: str) -> list[str]:
    """Inspect Python source without executing its imports."""
    tree = ast.parse(source)
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if is_forbidden_import(alias.name):
                    violations.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""

            if is_forbidden_import(module_name):
                violations.append(module_name)

            elif node.level > 0 and node.level > 1:
                # Package-relative imports escaping app.engine
                violations.append(f"relative import: level={node.level}")

    return violations


def test_engine_has_no_forbidden_imports():
    """All engine Python files must respect architecture boundaries."""
    python_files = list(ENGINE_DIR.rglob("*.py"))

    assert python_files, "No Python files found in app/engine"

    violations = []

    for file_path in python_files:
        source = file_path.read_text(encoding="utf-8")

        for forbidden in find_forbidden_imports(source):
            violations.append(f"{file_path}: {forbidden}")

    assert not violations, "\n".join(violations)


def test_boundary_checker_detects_forbidden_imports():
    """Verify that the checker catches intentional violations."""
    invalid_source = """
from fastapi import FastAPI
import sqlalchemy
from app.db.session import get_session
from app.modules.ai import assistant
from ..core import config
"""

    violations = find_forbidden_imports(invalid_source)

    assert "fastapi" in violations
    assert "sqlalchemy" in violations
    assert "app.db.session" in violations
    assert "app.modules.ai" in violations
    assert "relative import: level=2" in violations
