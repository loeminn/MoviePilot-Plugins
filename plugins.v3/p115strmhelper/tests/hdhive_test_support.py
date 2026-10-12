"""
RE0 测试的独立工具模块加载器
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


def load_resource_utils() -> ModuleType:
    """
    加载资源解析模块，避免插件 utils 与宿主同名包冲突

    :return ModuleType: 资源解析模块
    """
    path = Path(__file__).resolve().parents[1] / "utils" / "hdhive.py"
    spec = spec_from_file_location("_re0_resource_utils_test", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
