"""验证公开 Oper 模糊查询参数及已有事件循环下的查询"""

import ast
import asyncio
from pathlib import Path

import pytest


@pytest.mark.parametrize("active_loop", [False, True])
def test_history_query_uses_public_oper_with_escaped_wildcards(active_loop):
    path = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper/db_manager/moviepilot_transfer.py"
    source = ast.parse(path.read_text("utf8"))
    source.body = [n for n in source.body if not (isinstance(n, ast.ImportFrom) and n.module.startswith("app."))]
    calls = []
    class Oper:
        async def async_list_by_title(self, **kwargs):
            calls.append(kwargs)
            return ["record"]
    namespace = {"TransferHistoryOper": Oper, "jieba_cut": lambda path, **kw: ["a%", "b_"]}
    exec(compile(source, str(path), "exec"), namespace)
    query = namespace["TransferHBOper"]().get_transfer_his_by_path_title
    async def in_loop():
        return query("test")
    assert (asyncio.run(in_loop()) if active_loop else query("test")) == ["record"]
    assert calls == [dict(title="%a\\%%b\\_%", page=1, count=-1, wildcard=True)]
