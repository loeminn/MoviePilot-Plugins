"""验证任务执行及宿主重建服务时的插件实例归属"""

import ast
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class Plugin:
    """提供可弱引用的插件实例"""


@pytest.fixture
def scheduler():
    source = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper/service/one_shot.py"
    tree = ast.parse(source.read_text("utf8"))
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app.")
    )]
    register = MagicMock(return_value=True)
    namespace = {"add_plugin_once_job": register, "logger": MagicMock()}
    exec(compile(ast.fix_missing_locations(tree), str(source), "exec"), namespace)
    return namespace, register


def test_once_job_binds_owner_and_preserves_callback_arguments(scheduler):
    namespace, register = scheduler
    plugin = Plugin()
    helper = MagicMock()
    helper.backup.return_value = "done"
    namespace["bind_plugin_instance"](plugin)
    assert namespace["schedule_plugin_one_shot"]("backup", "备份", helper.backup, {"task_name": "test"}, 5)
    kwargs = dict(register.call_args.kwargs)
    callback = kwargs.pop("func")
    assert kwargs == dict(plugin_id="P115StrmHelper", job_id="backup", name="备份",
                          delay_seconds=5, func_kwargs={"task_name": "test"})
    assert callback.__self__ is plugin
    assert callback(**kwargs["func_kwargs"]) == "done"
    helper.backup.assert_called_once_with(task_name="test")


@pytest.mark.parametrize("replace_plugin", [False, True])
def test_real_host_rebuild_keeps_current_owner_only(scheduler, replace_plugin):
    host_path = os.environ.get("MOVIEPILOT_SOURCE")
    if not host_path:
        pytest.skip("设置 MOVIEPILOT_SOURCE 以执行真实宿主调度方法测试")
    source = Path(host_path) / "app/scheduler/oncejob.py"
    tree = ast.parse(source.read_text("utf8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                  and n.name == "_detach_live_plugin_once_jobs")
    namespace, register = scheduler
    plugin = Plugin()
    namespace["bind_plugin_instance"](plugin)
    assert namespace["schedule_plugin_one_shot"]("sync", "同步", MagicMock())
    callback = register.call_args.kwargs["func"]
    current = Plugin() if replace_plugin else plugin
    host_namespace = {"Any": object, "get_plugin_manager": lambda: SimpleNamespace(
        running_plugins={"P115StrmHelper": current})}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), host_namespace)
    job_id = "P115StrmHelper_once_sync"
    job = {"once": True, "pid": "P115StrmHelper", "_plugin_instance": callback.__self__}
    owner = SimpleNamespace(_jobs={job_id: job}, _is_plugin_once_job_pending=lambda *args: True)
    kept = host_namespace["_detach_live_plugin_once_jobs"](owner, "P115StrmHelper")
    assert kept == ({} if replace_plugin else {job_id: job})


def test_old_instance_stop_does_not_unbind_new_instance(scheduler):
    namespace, register = scheduler
    old, new = Plugin(), Plugin()
    namespace["bind_plugin_instance"](old)
    namespace["bind_plugin_instance"](new)
    namespace["unbind_plugin_instance"](old)
    assert namespace["schedule_plugin_one_shot"]("sync", "同步", MagicMock())
    assert register.call_args.kwargs["func"].__self__ is new


def test_stopped_instance_cannot_register_task(scheduler):
    namespace, register = scheduler
    plugin = Plugin()
    namespace["bind_plugin_instance"](plugin)
    namespace["unbind_plugin_instance"](plugin)
    assert namespace["schedule_plugin_one_shot"]("sync", "同步", MagicMock()) is False
    register.assert_not_called()


def test_saving_config_can_rebind_same_instance(scheduler):
    namespace, register = scheduler
    plugin = Plugin()
    namespace["bind_plugin_instance"](plugin)
    namespace["unbind_plugin_instance"](plugin)
    namespace["bind_plugin_instance"](plugin)
    assert namespace["schedule_plugin_one_shot"]("sync", "同步", MagicMock())
    assert register.call_args.kwargs["func"].__self__ is plugin
