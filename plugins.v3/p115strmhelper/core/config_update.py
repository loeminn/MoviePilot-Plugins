"""通过 V3 宿主保存配置并刷新插件运行态注册"""

from typing import Any, Dict

from app.application.plugin.management import refresh_plugin_registrations
from app.sdk.plugin import PluginManager

from .config import configer


def save_plugin_config(updates: Dict[str, Any]) -> None:
    """校验配置后更新宿主实例、事件、定时服务、命令及动态路由"""
    if not isinstance(updates, dict):
        raise ValueError("配置必须是 JSON 对象")
    plugin_id = "P115StrmHelper"
    manager = PluginManager()
    with manager.mutation(f"更新插件 {plugin_id} 配置"):
        config = configer.model_dump(mode="json")
        config.update(updates)
        config = configer.model_validate(config).model_dump(mode="json")
        if not manager.save_plugin_config(plugin_id, config):
            raise RuntimeError("插件配置保存失败")
        manager.init_plugin(plugin_id, conf=config)
        refresh_plugin_registrations(plugin_id)
