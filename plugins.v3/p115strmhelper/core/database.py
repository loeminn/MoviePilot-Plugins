"""在业务服务启动前完成旧库导入和宿主数据库准备"""

from pathlib import Path
from threading import RLock
from typing import Any, Dict

from app.sdk.config import settings
from app.db.plugin.registry import ensure_database

from ..db_manager import bind_handle
from .legacy_migration import import_legacy_database
from .config import ConfigManager
from .postgres_import import import_postgres_database

_prepare_lock = RLock()


def prepare_database(plugin: Any, config: Dict[str, Any]) -> None:
    """先保全旧库，由宿主建库并完成对应数据库类型的数据导入"""
    with _prepare_lock:
        database_type = str(settings.DB_TYPE).lower()
        if database_type not in ("sqlite", "postgresql"):
            raise RuntimeError(f"不支持的宿主数据库类型：{database_type}")
        migrations = Path(plugin.get_database_migrations())
        source = Path(config["PLUGIN_DB_PATH"])
        target = plugin.get_data_path() / "plugin.db"
        if database_type == "postgresql" and target.exists():
            source = target
        if (database_type == "sqlite" and not target.exists() and not source.exists()
                and source.resolve() != ConfigManager._get_default_plugin_db_path().resolve()):
            raise RuntimeError(f"自定义旧库路径不存在，拒绝以空库启动：{source}")
        if database_type == "sqlite":
            import_legacy_database(source, target, migrations)
        # 宿主默认在 init_plugin 返回后建表，业务线程启动前须提前完成同一准备流程
        ensure_database(plugin.__class__.__name__, migrations=migrations)
        handle = plugin.get_database()
        if database_type == "postgresql":
            import_postgres_database(
                handle, source, migrations, plugin.get_data_path(),
                allow_missing=source.resolve() == ConfigManager._get_default_plugin_db_path().resolve(),
            )
        bind_handle(handle)
