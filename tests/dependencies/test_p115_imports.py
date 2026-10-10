"""使用真实依赖验证启动导入及并发接口，不连接 115 账号"""

import ast
import asyncio
import importlib
from inspect import signature
from pathlib import Path
from typing import Tuple

import concurrenttools
import pytest


PLUGIN = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper"

def test_all_plugin_p115_imports_resolve() -> None:
    """
    验证全部插件引用的客户端符号可直接导入，无需修改共享依赖
    """

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


def test_thread_map_results_and_errors() -> None:
    """
    验证新版同步并发接口的结果及异常传播
    """

    assert list(concurrenttools.thread_conmap(lambda x: x * 2, [1, 2, 3], max_workers=2)) == [2, 4, 6]
    with pytest.raises(ZeroDivisionError):
        list(concurrenttools.thread_conmap(lambda x: 1 / x, [0], max_workers=1))


def test_async_map_results_and_errors() -> None:
    """
    验证新版异步并发接口的结果及异常传播
    """

    async def _run() -> None:
        async def _double(value: int) -> int:
            return value * 2

        async def _fail(value: int) -> None:
            raise ValueError("expected")

        result = [value async for value in concurrenttools.async_conmap(_double, [1, 2, 3], max_workers=2)]
        assert result == [2, 4, 6]
        failed = False
        try:
            [value async for value in concurrenttools.async_conmap(_fail, [1], max_workers=1)]
        except* ValueError as errors:
            assert all(str(error) == "expected" for error in errors.exceptions)
            failed = True
        assert failed

    asyncio.run(_run())


@pytest.mark.parametrize(
    "module_name,name,parameters",
    [
        ("iterdir", "iter_files", ("with_path", "with_ancestors", "order", "max_workers")),
        ("iterdir", "iter_files_skim", ("with_path", "with_ancestors")),
        ("iterdir", "share_iterdir", ("order", "share_code", "cid")),
        ("iterdir", "traverse_tree", ("with_path", "id_to_dirnode", "async_")),
        ("iter_nodes", "iter_nodes", ("payload", "page_size")),
    ],
)
def test_iterator_parameters_are_consumed_by_client(
    module_name: str, name: str, parameters: Tuple[str, ...]
) -> None:
    """
    验证路径及排序参数由真实客户端消费，避免误透传为 HTTP 请求参数
    """

    function = getattr(importlib.import_module(f"p115client.tool.{module_name}"), name)
    declared = signature(function).parameters
    assert all(parameter in declared for parameter in parameters)
