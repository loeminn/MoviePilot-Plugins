"""检查一次性任务通过宿主公开接口注册"""

import ast
from pathlib import Path
from unittest.mock import MagicMock


def test_once_job_uses_host_api_without_private_scheduler():
    source = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper/service/one_shot.py"
    tree = ast.parse(source.read_text("utf8"))
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    tree.body.insert(0, ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0))
    register = MagicMock(return_value=True)
    namespace = {"add_plugin_once_job": register, "logger": MagicMock()}
    exec(compile(ast.fix_missing_locations(tree), str(source), "exec"), namespace)
    callback = lambda: None
    assert namespace["schedule_plugin_one_shot"]("backup", "备份", callback, {"test": 1}, 5)
    register.assert_called_once_with(plugin_id="P115StrmHelper", job_id="backup", func=callback,
                                     name="备份", delay_seconds=5, func_kwargs={"test": 1})
