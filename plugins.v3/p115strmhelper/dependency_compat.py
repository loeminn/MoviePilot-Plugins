"""兼容 p115client 0.0.9.6.5.1 使用的旧并发接口名称"""

from importlib.metadata import version

import concurrenttools


def ensure_concurrenttools_compat() -> None:
    """为已验证的 concurrenttools 0.1.9 补齐旧名称，保留已有实现"""
    # 0.1.9 的模块 __version__ 仍为 0.1.8，必须读取发行包元数据
    if version("python-concurrenttools") != "0.1.9":
        return
    for old_name, new_name in (
        ("threadpool_map", "thread_conmap"),
        ("taskgroup_map", "async_conmap"),
    ):
        if not hasattr(concurrenttools, old_name):
            setattr(concurrenttools, old_name, getattr(concurrenttools, new_name))
