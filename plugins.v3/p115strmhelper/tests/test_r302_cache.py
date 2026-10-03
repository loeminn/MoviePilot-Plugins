"""
302 缓存存在性查询测试
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from unittest import IsolatedAsyncioTestCase


def _load_cache_class() -> Any:
    path = Path(__file__).resolve().parents[1] / "core" / "cache.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cache_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "R302Cache"
    )
    namespace: Dict[str, Any] = {"Optional": Optional}
    exec(
        compile(ast.Module(body=[cache_class], type_ignores=[]), str(path), "exec"),
        namespace,
    )
    return namespace["R302Cache"]


class TestR302Cache(IsolatedAsyncioTestCase):
    """
    隔离宿主缓存依赖，验证实际查询方法的遍历次数和键边界
    """

    async def test_lookup_stops_after_first_match(self) -> None:
        """
        命中目标文件后不再读取后续缓存条目
        """
        cache_type = _load_cache_class()
        cache = cache_type.__new__(cache_type)
        cache.region = "test"
        visited: List[str] = []

        async def items(region: str) -> AsyncIterator[Tuple[str, str]]:
            self.assertEqual(region, "test")
            for key in ("other○UA", "target○UA", "target○UA2", "last○UA"):
                visited.append(key)
                yield key, "url"

        cache._cache = SimpleNamespace(items=items)
        self.assertTrue(await cache.has_pick_code("target"))
        self.assertEqual(visited, ["other○UA", "target○UA"])

    async def test_empty_and_similar_prefixes_do_not_match(self) -> None:
        """
        空缓存以及只有相似前缀的缓存均不命中
        """
        cache_type = _load_cache_class()
        cache = cache_type.__new__(cache_type)
        cache.region = "test"
        for keys in ([], ["target", "target-extra○UA", "target2○UA"]):
            with self.subTest(keys=keys):
                async def items(region: str) -> AsyncIterator[Tuple[str, str]]:
                    for key in keys:
                        yield key, "url"

                cache._cache = SimpleNamespace(items=items)
                self.assertFalse(await cache.has_pick_code("target"))
