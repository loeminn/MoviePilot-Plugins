"""
302 缓存存在性查询测试
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock
from urllib.parse import parse_qsl, unquote, urlsplit


def _load_cache_class() -> Any:
    path = Path(__file__).resolve().parents[1] / "core" / "cache.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cache_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "R302Cache"
    )
    namespace: Dict[str, Any] = {
        "Optional": Optional, "Dict": Dict, "List": List, "Any": Any,
        "unquote": unquote, "urlsplit": urlsplit, "logger": Mock(),
        "parse_qsl": parse_qsl,
    }
    exec(
        compile(ast.Module(body=[cache_class], type_ignores=[]), str(path), "exec"),
        namespace,
    )
    return namespace["R302Cache"]


class TestR302Cache(IsolatedAsyncioTestCase):
    """
    隔离宿主缓存依赖，验证实际查询方法的遍历次数和键边界
    """

    def _make_cache(self, values, expired=(), failures=()):
        cache_type = _load_cache_class()
        cache = cache_type.__new__(cache_type)
        cache.region = "r302-test"
        calls = []

        async def items(region):
            self.assertEqual(region, cache.region)
            for item in list(values.items()):
                yield item

        async def get(key, region):
            self.assertEqual(region, cache.region)
            return None if key in expired else values.get(key)

        async def delete(key, region):
            self.assertEqual(region, cache.region)
            calls.append(key)
            if key in failures:
                raise RuntimeError("backend unavailable")
            values.pop(key, None)

        cache._cache = SimpleNamespace(items=items, get=get, delete=delete)
        return cache, calls

    async def test_listing_filters_expired_and_searches_decoded_names(self) -> None:
        """
        只返回有效缓存并支持中文文件名和 UA 搜索
        """
        cache, _ = self._make_cache({
            "file○UA1": "https://example.test/%E7%94%B5%E5%BD%B1.mkv?t=1",
            "file○UA2○suffix": "https://example.test/other.mkv",
            "expired○UA": "https://example.test/expired.mkv",
            "sharecodepass123○NoUA": "https://example.test/",
        }, expired={"expired○UA"})
        result = await cache.list_entries()
        self.assertEqual(result["total"], 3)
        self.assertEqual((await cache.list_entries("电影"))["items"][0]["file_name"], "电影.mkv")
        self.assertEqual((await cache.list_entries("ua2"))["items"][0]["user_agent"], "UA2○suffix")
        self.assertEqual((await cache.list_entries("sharecode"))["items"][0]["file_name"], "sharecodepass123")
        self.assertEqual((await cache.list_entries("missing"))["items"], [])

    async def test_expiry_matches_redirect_cache_deadline(self) -> None:
        """
        到期时间与直链提前五分钟的缓存规则一致，异常时间返回空值
        """
        for query, expected in (
            ("t=4102444800", 4102444500),
            ("foo=1&t=4102444800&t=4200000000", 4102444500),
            ("t=invalid", None), ("t=", None), ("other=1", None), ("t=1", None),
        ):
            with self.subTest(query=query):
                cache, _ = self._make_cache({"file○UA": f"https://example.test/movie.mkv?{query}"})
                result = await cache.list_entries(keyword="movie")
                self.assertEqual(result["items"][0]["expires_at"], expected)

    async def test_pagination_and_page_clamping(self) -> None:
        """
        列表排序稳定且删除末页后返回有效页码
        """
        values = {f"{i:03}○UA": f"https://example.test/{i}" for i in reversed(range(21))}
        cache, _ = self._make_cache(values)
        result = await cache.list_entries(page=2)
        self.assertEqual(result["items"][0]["key"], "020○UA")
        await cache.delete_entries(["020○UA"])
        result = await cache.list_entries(page=2)
        self.assertEqual((result["page"], result["total"]), (1, 20))
        values.clear()
        self.assertEqual(await cache.list_entries(page=5), {"items": [], "total": 0, "page": 1})

    async def test_duplicate_scan_entries_are_counted_once(self) -> None:
        """
        Redis 扫描重复返回同一键时列表只显示一次
        """
        cache, _ = self._make_cache({"file○UA": "https://example.test/movie.mkv"})

        async def items(region):
            for _ in range(2):
                yield "file○UA", "https://example.test/movie.mkv"

        cache._cache.items = items
        result = await cache.list_entries()
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["items"]), 1)

    async def test_silently_failed_delete_is_not_reported_as_processed(self) -> None:
        """
        后端吞掉删除错误但键仍存在时报告失败
        """
        cache, _ = self._make_cache({"file○UA": "url"})

        async def delete(key, region):
            return None

        cache._cache.delete = delete
        self.assertEqual(
            await cache.delete_entries(["file○UA", "missing○UA"]),
            {"processed_keys": ["missing○UA"], "failed_keys": ["file○UA"]},
        )

    async def test_exact_deletion_deduplication_and_partial_failure(self) -> None:
        """
        删除精确匹配完整键，去重并独立报告失败
        """
        values = {key: "url" for key in ("file○UA", "file○UA2", "file2○UA", "failed○UA")}
        cache, calls = self._make_cache(values, failures={"failed○UA"})
        result = await cache.delete_entries(["file○UA", "file○UA", "missing○UA", "failed○UA"])
        self.assertEqual(result["processed_keys"], ["file○UA", "missing○UA"])
        self.assertEqual(result["failed_keys"], ["failed○UA"])
        self.assertEqual(calls, ["file○UA", "missing○UA", "failed○UA"])
        self.assertEqual(set(values), {"file○UA2", "file2○UA", "failed○UA"})

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
