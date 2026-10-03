"""直接执行实际配置字段和验证器，检查隐私默认值与旧配置迁移"""

import ast
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins.v3/p115strmhelper"


def config_model():
    tree = ast.parse((PLUGIN / "core/config.py").read_text("utf8"))
    original = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ConfigManager")
    fields = {"error_info_upload", "upload_share_info", "upload_offline_info", "pan_transfer_takeover", "model_config"}
    selected = [node for node in original.body if
                (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in fields)
                or (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "model_config" for t in node.targets))
                or (isinstance(node, ast.FunctionDef) and node.name == "_disable_v2_takeover")]
    cls = ast.ClassDef(name="Config", bases=[ast.Name(id="BaseModel", ctx=ast.Load())], keywords=[],
                       body=selected, decorator_list=[])
    namespace = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field,
                     field_validator=field_validator, Any=Any, Literal=Literal)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), "config-fields", "exec"), namespace)
    return namespace["Config"]


def test_new_config_does_not_opt_into_reporting():
    config = config_model()()
    assert config.error_info_upload is False
    assert config.upload_share_info is False
    assert config.upload_offline_info is False


def test_explicit_reporting_preferences_preserved_but_old_takeover_disabled():
    config = config_model()(error_info_upload=True, upload_share_info=True,
                            upload_offline_info=True, pan_transfer_takeover=True)
    assert config.error_info_upload is True
    assert config.upload_share_info is True
    assert config.upload_offline_info is True
    assert config.pan_transfer_takeover is False


def test_service_cannot_load_legacy_takeover():
    source = (PLUGIN / "service/__init__.py").read_text("utf8")
    assert "TransferChainPatcher" not in source
    assert "from ..helper.transfer" not in source


def test_manifest_and_source_version_match():
    entry = json.loads((ROOT / "package.v3.json").read_text("utf8"))["P115StrmHelper"]
    namespace = {}
    exec((PLUGIN / "version.py").read_text("utf8"), namespace)
    assert entry["version"] == namespace["VERSION"] == "3.1.6"
    assert entry["system_version"] == ">=3.1.0"
    assert entry["release"] is True


def test_assignment_cannot_reenable_legacy_takeover():
    config = config_model()()
    config.pan_transfer_takeover = True
    assert config.pan_transfer_takeover is False
