"""执行插件持久化方法，验证宿主插件存储及实例绑定"""

import ast
from pathlib import Path
from typing import Any, Optional
from weakref import ref

from pydantic import BaseModel, PrivateAttr

ROOT = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper"


def test_config_persistence_uses_bound_plugin_storage():
    source = ast.parse((ROOT / "core/config.py").read_text("utf8"))
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "ConfigManager")
    methods = {"bind_plugin", "_plugin", "update_plugin_config"}
    cls.body = [n for n in cls.body if
                (isinstance(n, ast.FunctionDef) and n.name in methods)
                or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "_plugin_ref")]
    namespace = dict(BaseModel=BaseModel, PrivateAttr=PrivateAttr, Any=Any, Optional=Optional, ref=ref)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), "config", "exec"), namespace)
    class Config(namespace["ConfigManager"]):
        enabled: bool = False

        def update_config(self, updates):
            self.enabled = updates["enabled"]
            return True

    config = Config()
    storage = {}
    class Owner:
        def update_config(self, data):
            storage.update(data)
            return True

        def get_config(self):
            return dict(storage)

    owner = Owner()
    config.bind_plugin(owner)
    config.update_config({"enabled": True})
    config.update_plugin_config()
    assert storage == {"enabled": True}
    assert owner.get_config() == {"enabled": True}


def test_clone_rejected_before_shared_configuration_changes():
    tree = ast.parse((ROOT / "__init__.py").read_text("utf8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "P115StrmHelper")
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    guard = next(n for n in init.body if isinstance(n, ast.If) and "__name__" in ast.unparse(n.test))
    bind = next(i for i, n in enumerate(init.body) if "configer.bind_plugin" in ast.unparse(n))
    assert init.body.index(guard) < bind
    import pytest
    with pytest.raises(RuntimeError, match="不支持虚拟分身"):
        exec(compile(ast.Module(body=[guard], type_ignores=[]), "clone-guard", "exec"), {"self": type("Clone", (), {})()})
