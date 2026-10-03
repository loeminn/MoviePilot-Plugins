"""以 SQLite 一致性快照导入旧库，保留源库并在校验后原子落盘"""

import os
import sqlite3
from configparser import ConfigParser
from contextlib import closing
from pathlib import Path
from time import monotonic
from typing import Dict
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

TABLES = ("files", "folders", "life_event", "open_files", "open_folders")


def _counts(connection: sqlite3.Connection) -> Dict[str, int]:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"files", "folders"}.issubset(tables):
        raise RuntimeError("旧数据库缺少 files/folders 表，拒绝将非插件库导入")
    return {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in TABLES if table in tables}


def _upgrade_copy(path: Path, migrations: Path) -> None:
    config = Config()
    config.file_config = ConfigParser(interpolation=None)
    config.set_main_option("script_location", str(migrations))
    config.set_main_option("sqlalchemy.url", URL.create("sqlite", database=str(path)).render_as_string(hide_password=False))
    command.upgrade(config, "head")


def import_legacy_database(source: Path, target: Path, migrations: Path) -> bool:
    """首次导入旧 SQLite 库，失败保留原库且不留下半成品目标库"""
    if target.exists():
        with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if tables:
            _validate_existing(target)
            return False
        raise RuntimeError(f"目标数据库为空，请先确认并移走该空文件后重试：{target}")
    if not source.exists():
        return False
    if not migrations.is_absolute() or not migrations.is_dir():
        raise RuntimeError("数据库迁移目录必须是存在的绝对路径")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"plugin.db.migrating.{uuid4().hex}.tmp")
    deadline = monotonic() + 120

    def progress(status: int, remaining: int, total: int) -> None:
        if monotonic() > deadline:
            raise TimeoutError("旧库快照超过 120 秒，请停止其他写入后重试")

    try:
        # backup API 包含 WAL 中的已提交数据，无需 checkpoint 或复制正在变化的主文件
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)) as src:
            with closing(sqlite3.connect(temporary)) as dst:
                src.backup(dst, pages=1024, progress=progress, sleep=0.05)
                if dst.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise RuntimeError("旧库快照完整性检查失败")
                counts = _counts(dst)
        _upgrade_copy(temporary, migrations)
        with closing(sqlite3.connect(temporary)) as migrated:
            if migrated.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise RuntimeError("升级后的数据库完整性检查失败")
            new_counts = _counts(migrated)
            if any(new_counts[table] != count for table, count in counts.items()):
                raise RuntimeError("旧库升级前后行数发生变化，拒绝继续迁移")
        if target.exists():
            raise RuntimeError("迁移期间目标库已出现，拒绝覆盖")
        os.replace(temporary, target)
        return True
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(temporary) + suffix).unlink(missing_ok=True)


def _validate_existing(target: Path) -> None:
    with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("现有插件数据库完整性检查失败，拒绝覆盖")
        _counts(connection)
