"""使用真实依赖验证启动导入及并发接口，不连接 115 账号"""

import ast
import asyncio
import importlib
from pathlib import Path
import runpy

import concurrenttools
import pytest


PLUGIN = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper"
ensure_compat = runpy.run_path(str(PLUGIN / "dependency_compat.py"))[
    "ensure_concurrenttools_compat"
]


def test_bootstrap_runs_before_other_imports():
    tree = ast.parse((PLUGIN / "__init__.py").read_text("utf8"))
    assert isinstance(tree.body[0], ast.ImportFrom)
    assert tree.body[0].module == "dependency_compat"
    assert isinstance(tree.body[1], ast.Expr)
    assert tree.body[1].value.func.id == "ensure_concurrenttools_compat"


def test_all_plugin_p115_imports_resolve():
    ensure_compat()
    imports = set()
    for path in PLUGIN.rglob("*.py"):
        if "tests" in path.relative_to(PLUGIN).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text("utf8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("p115client"):
                imports.add((node.module, tuple(alias.name for alias in node.names)))
    for module_name, names in sorted(imports):
        module = importlib.import_module(module_name)
        for name in names:
            assert hasattr(module, name), f"{module_name}.{name}"


def test_compat_is_idempotent_and_preserves_existing_functions():
    ensure_compat()
    original = (concurrenttools.threadpool_map, concurrenttools.taskgroup_map)
    ensure_compat()
    assert original == (concurrenttools.threadpool_map, concurrenttools.taskgroup_map)


def test_thread_map_results_and_errors():
    ensure_compat()
    assert list(concurrenttools.threadpool_map(lambda x: x * 2, [1, 2, 3], max_workers=2)) == [2, 4, 6]
    with pytest.raises(ZeroDivisionError):
        list(concurrenttools.threadpool_map(lambda x: 1 / x, [0], max_workers=1))


def test_async_map_results_and_errors():
    ensure_compat()

    async def run():
        async def double(value):
            return value * 2

        async def fail(value):
            raise ValueError("expected")

        result = [value async for value in concurrenttools.taskgroup_map(double, [1, 2, 3], max_workers=2)]
        assert result == [2, 4, 6]
        failed = False
        try:
            [value async for value in concurrenttools.taskgroup_map(fail, [1], max_workers=1)]
        except* ValueError as errors:
            assert all(str(error) == "expected" for error in errors.exceptions)
            failed = True
        assert failed

    asyncio.run(run())
