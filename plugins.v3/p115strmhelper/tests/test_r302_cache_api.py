"""
直链缓存管理接口的请求校验与结果测试
"""

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient


def _load_schema(name):
    path = Path(__file__).resolve().parents[1] / "schemas" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"r302_test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestR302CacheApi(TestCase):
    """
    隔离宿主服务，使用实际 API 方法验证 HTTP 契约
    """

    def setUp(self) -> None:
        """
        创建仅包含缓存管理接口的测试应用
        """
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "api.py").read_text(encoding="utf-8"))
        api_class = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        names = {"list_302_cache_api", "delete_302_cache_api"}
        methods = [node for node in api_class.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
        for method in methods:
            method.decorator_list = []
        self.cache = SimpleNamespace(
            list_entries=AsyncMock(return_value={"items": [], "total": 0, "page": 1}),
            delete_entries=AsyncMock(return_value={"processed_keys": ["file○UA"], "failed_keys": []}),
        )
        namespace = {
            "Query": Query,
            "ApiResponse": _load_schema("api").ApiResponse,
            "DeleteR302CachePayload": _load_schema("r302_cache").DeleteR302CachePayload,
            "r302cacher": self.cache,
        }
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(root / "api.py"), "exec"), namespace)
        app = FastAPI()
        app.get("/list_302_cache")(namespace["list_302_cache_api"])
        app.post("/delete_302_cache")(namespace["delete_302_cache_api"])
        self.client = TestClient(app)

    def test_list_defaults_and_validation(self) -> None:
        """
        默认分页参数及非法查询参数均按契约处理
        """
        response = self.client.get("/list_302_cache")
        self.assertEqual(response.status_code, 200)
        self.cache.list_entries.assert_awaited_once_with("", 1, 20)
        for query in ("page=0", "page_size=0", "page_size=101"):
            self.assertEqual(self.client.get(f"/list_302_cache?{query}").status_code, 422)

    def test_delete_validation_and_partial_results(self) -> None:
        """
        空列表无副作用且部分失败保留逐键结果
        """
        for payload in ({}, {"keys": []}, {"keys": [1]}, {"keys": ["key"] * 101}):
            self.assertEqual(self.client.post("/delete_302_cache", json=payload).status_code, 422)
        self.cache.delete_entries.assert_not_awaited()
        self.cache.delete_entries.return_value = {"processed_keys": ["file○UA"], "failed_keys": ["file○UA2"]}
        response = self.client.post("/delete_302_cache", json={"keys": ["file○UA", "file○UA2"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], self.cache.delete_entries.return_value)
        self.assertIn("失败 1", response.json()["msg"])

    def test_routes_require_bearer_authentication(self) -> None:
        """
        两个新增路由均注册宿主鉴权要求
        """
        path = Path(__file__).resolve().parents[1] / "__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            values = {
                key.value: value.value for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
            }
            if values.get("path") in ("/list_302_cache", "/delete_302_cache"):
                found[values["path"]] = values.get("auth")
        self.assertEqual(found, {"/list_302_cache": "bear", "/delete_302_cache": "bear"})
