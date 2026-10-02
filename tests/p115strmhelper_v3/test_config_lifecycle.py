"""执行真实保存方法和宿主路由注册器，验证保存后的运行态更新"""

import ast
import asyncio
import os
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import runpy
from threading import Event, Lock, get_ident
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import Mock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper"


class Config(BaseModel):
    enabled: bool = True
    cookies: str = "account-A"
    cron_full_sync_strm: str = "0 1 * * *"
    timing_full_sync_strm: bool = True
    full_sync_strm_paths: str = "/local#/remote"

    @property
    def share_strm_cleanup_config(self):
        return SimpleNamespace(timing_share_strm_cleanup=False)

    def __getattr__(self, name):
        return False

    def update_config(self, data):
        validated = self.model_validate(data)
        for key, value in validated.model_dump().items():
            setattr(self, key, value)

    def update_plugin_config(self):
        return True


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text("utf8"))
    selected = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(path), "exec"), namespace)


@pytest.fixture
def runtime():
    config = Config()
    calls = []
    storage = {}
    manager = Mock()

    @contextmanager
    def mutation(operation):
        calls.append("enter")
        try:
            yield
        finally:
            calls.append("exit")

    def persist(plugin_id, data):
        assert plugin_id == "P115StrmHelper"
        calls.append("persist")
        storage.update(data)
        return True

    manager.mutation.side_effect = mutation
    manager.save_plugin_config.side_effect = persist
    helper = dict(Any=Any, Dict=Dict, configer=config, PluginManager=lambda: manager,
                  _config_update_lock=Lock(),
                  refresh_plugin_registrations=Mock())
    load_functions(PLUGIN / "core/config_update.py", {"save_plugin_config"}, helper)
    return SimpleNamespace(config=config, manager=manager, helper=helper, calls=calls, storage=storage)


def test_save_refreshes_real_routes_and_declared_cron_services(runtime):
    host_path = os.environ.get("MOVIEPILOT_SOURCE")
    if not host_path:
        pytest.skip("MOVIEPILOT_SOURCE required for real host route registry")
    registry_type = runpy.run_path(str(Path(host_path) / "app/adapters/web/plugin/routes.py"))["FastAPIDynamicRouteRegistry"]

    class Api:
        def __init__(self, client):
            self._client = client

        def probe(self):
            return {"client": self._client}

    service = Mock()
    service.init_service.side_effect = lambda: setattr(service, "client", runtime.config.cookies) or True
    namespace = dict(Api=Api, configer=runtime.config, servicer=service, Dict=Dict, List=list, Any=Any,
                     Request=Request, to_thread=asyncio.to_thread, save_plugin_config=runtime.helper["save_plugin_config"],
                     i18n=Mock(), sentry_manager=Mock(), bind_plugin_instance=Mock(), logger=Mock(),
                     U115Patcher=Mock(), P115DiskPatcher=Mock(), AppVerPatcher=Mock(), MCPManager=Mock(),
                     CronTrigger=SimpleNamespace(from_crontab=lambda value: value))
    load_functions(PLUGIN / "__init__.py", {"init_plugin", "get_service", "_save_config_api"}, namespace)
    owner = type("Owner", (), {name: namespace[name] for name in ("init_plugin", "get_service", "_save_config_api")})()
    owner.stop_service = Mock()
    owner.init_database = Mock()
    owner.init_plugin(runtime.config.model_dump())
    app = FastAPI()
    registry = registry_type(app, lambda: ["P115StrmHelper"], lambda _: [
        {"path": "/P115StrmHelper/probe", "endpoint": owner.api.probe, "methods": ["GET"], "allow_anonymous": True},
    ], lambda: None, lambda: None, "/api/v1/plugin", Mock())
    jobs = {}

    def refresh(plugin_id):
        runtime.calls.append("refresh")
        jobs.clear()
        if runtime.config.enabled:
            jobs.update({job["id"]: job["trigger"] for job in owner.get_service()})
        registry.update(plugin_id, "add")

    def initialize(plugin_id, conf):
        runtime.calls.append("initialize")
        owner.init_plugin(conf)

    runtime.manager.init_plugin.side_effect = initialize
    runtime.helper["refresh_plugin_registrations"] = refresh
    refresh("P115StrmHelper")
    runtime.calls.clear()
    job_id = "P115StrmHelper_full_sync_strm_files"
    assert jobs[job_id] == "0 1 * * *"
    old_api = owner.api

    async def save(data):
        async def payload():
            return data
        return await owner._save_config_api(SimpleNamespace(json=payload))

    result = asyncio.run(save({"cookies": "account-B", "cron_full_sync_strm": "0 3 * * *"}))
    assert result["code"] == 0
    assert runtime.calls == ["enter", "persist", "initialize", "refresh", "exit"]
    assert owner.api is not old_api
    with TestClient(app) as client:
        assert client.get("/api/v1/plugin/P115StrmHelper/probe").json() == {"client": "account-B"}
    assert jobs[job_id] == "0 3 * * *"
    assert asyncio.run(save({"timing_full_sync_strm": False}))["code"] == 0
    assert job_id not in jobs
    assert asyncio.run(save({"timing_full_sync_strm": True}))["code"] == 0
    assert job_id in jobs
    assert asyncio.run(save({"enabled": False}))["code"] == 0
    assert jobs == {}


@pytest.mark.parametrize("updates", [[], {"enabled": "invalid-boolean"}])
def test_invalid_config_does_not_write_or_initialize(runtime, updates):
    with pytest.raises(ValueError):
        runtime.helper["save_plugin_config"](updates)
    runtime.manager.save_plugin_config.assert_not_called()
    runtime.manager.init_plugin.assert_not_called()
    assert runtime.config.cookies == "account-A"


def test_failed_persistence_does_not_initialize_or_refresh(runtime):
    runtime.manager.save_plugin_config.side_effect = lambda *args: False
    with pytest.raises(RuntimeError, match="配置保存失败"):
        runtime.helper["save_plugin_config"]({"cookies": "account-B"})
    runtime.manager.init_plugin.assert_not_called()
    runtime.helper["refresh_plugin_registrations"].assert_not_called()


def test_api_moves_blocking_save_off_event_loop_and_reports_refresh_failure():
    main_thread = get_ident()
    def fail(data):
        assert get_ident() != main_thread
        raise RuntimeError("路由刷新失败")
    namespace = dict(Request=Request, Dict=Dict, to_thread=asyncio.to_thread, save_plugin_config=fail)
    load_functions(PLUGIN / "__init__.py", {"_save_config_api"}, namespace)
    async def payload():
        return {}
    result = asyncio.run(namespace["_save_config_api"](None, SimpleNamespace(json=payload)))
    assert result["code"] == 1
    assert "路由刷新失败" in result["msg"]


def test_concurrent_partial_saves_preserve_both_changes(runtime):
    first_refresh = Event()
    second_waiting = Event()
    release_first = Event()
    lock = runtime.helper["_config_update_lock"]

    class ObservedLock:
        def __enter__(self):
            if lock.locked():
                second_waiting.set()
            lock.acquire()

        def __exit__(self, *args):
            lock.release()

    runtime.helper["_config_update_lock"] = ObservedLock()
    runtime.manager.init_plugin.side_effect = lambda plugin_id, conf: runtime.config.update_config(conf)
    refreshed = []

    def refresh(plugin_id):
        refreshed.append(runtime.config.model_dump())
        if len(refreshed) == 1:
            first_refresh.set()
            assert release_first.wait(5)

    runtime.helper["refresh_plugin_registrations"] = refresh
    save = runtime.helper["save_plugin_config"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save, {"cookies": "account-B"})
        try:
            assert first_refresh.wait(5)
            second = pool.submit(save, {"cron_full_sync_strm": "0 3 * * *"})
            assert second_waiting.wait(5)
            assert runtime.manager.save_plugin_config.call_count == 1
        finally:
            release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert runtime.storage == runtime.config.model_dump()
    assert runtime.storage["cookies"] == "account-B"
    assert runtime.storage["cron_full_sync_strm"] == "0 3 * * *"
    assert refreshed[-1] == runtime.storage


def test_refresh_failure_releases_save_lock(runtime):
    runtime.helper["refresh_plugin_registrations"].side_effect = RuntimeError("刷新失败")
    with pytest.raises(RuntimeError, match="刷新失败"):
        runtime.helper["save_plugin_config"]({"cookies": "account-B"})
    assert runtime.helper["_config_update_lock"].acquire(blocking=False)
    runtime.helper["_config_update_lock"].release()
