from types import MethodType
from typing import Any, Callable, Dict, Optional
from weakref import ReferenceType, ref

from app.sdk.logging import logger
from app.sdk.scheduler import add_plugin_once_job


_plugin_instances: Dict[str, ReferenceType] = {}


def bind_plugin_instance(instance: Any, pid: str = "P115StrmHelper") -> None:
    """绑定一次性任务所属的主插件实例，供宿主判断重载后的任务有效性"""
    _plugin_instances[pid] = ref(instance)


def unbind_plugin_instance(instance: Any, pid: str = "P115StrmHelper") -> None:
    """停止时解除当前实例绑定，避免旧实例影响新实例"""
    current = _plugin_instances.get(pid)
    if current is not None and current() is instance:
        _plugin_instances.pop(pid, None)


def schedule_plugin_one_shot(
    service_id: str,
    name: str,
    func: Callable,
    func_kwargs: Optional[Dict[str, Any]] = None,
    delay_sec: int = 3,
    pid: str = "P115StrmHelper",
    provider_name: str = "115网盘STRM助手",
) -> bool:
    """
    向 MoviePilot 主调度器注册一次性延迟任务

    :param service_id (str): 插件内唯一服务 ID（与 pid 组合为 job_id）
    :param name (str): 任务显示名称
    :param func (Callable): 执行函数
    :param func_kwargs (Dict): 传入 func 的关键字参数
    :param delay_sec (int): 延迟秒数
    :param pid (str): 插件 ID
    :param provider_name (str): 任务提供方名称

    :return bool: 注册成功返回 True
    """
    try:
        instance_ref = _plugin_instances.get(pid)
        instance = instance_ref() if instance_ref is not None else None
        if instance is None:
            logger.error(f"【调度】插件实例未绑定，无法注册一次性任务: {name}")
            return False

        def _run(owner: Any, **kwargs: Any) -> Any:
            return func(**kwargs)

        return add_plugin_once_job(
            plugin_id=pid,
            job_id=service_id,
            func=MethodType(_run, instance),
            name=name,
            delay_seconds=delay_sec,
            func_kwargs=func_kwargs or {},
        )
    except Exception as e:
        logger.error(f"【调度】注册一次性任务失败: {name}, {e}", exc_info=True)
        return False
