import ast
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[1] / "src" / "app"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_delivery_modules_depend_on_ports_not_concrete_adapters() -> None:
    delivery_modules = [
        APPLICATION_ROOT / "dependencies.py",
        *sorted((APPLICATION_ROOT / "routes").glob("*.py")),
    ]

    for path in delivery_modules:
        imports = imported_modules(path)
        assert "app.gateway" not in imports, path
        assert "app.rate_limit" not in imports, path


def test_ports_do_not_depend_on_framework_or_infrastructure_packages() -> None:
    imports = imported_modules(APPLICATION_ROOT / "ports.py")

    assert not imports.intersection({"fastapi", "httpx2", "redis", "redis.asyncio"})
