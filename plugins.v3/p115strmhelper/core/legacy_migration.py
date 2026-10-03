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
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Connection

TABLES = ("files", "folders", "life_event", "open_files", "open_folders")
LEGACY_REVISIONS = {"294b0079357e", "2606909750bf", "d8dccb5dc598", "c76c9a1f52dc"}


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


def _upgrade_locked(connection: Connection, migrations: Path) -> None:
    """在调用方持有的 SQLite 写事务内运行迁移，不自行提交"""
    config = Config()
    config.file_config = ConfigParser(interpolation=None)
    config.set_main_option("script_location", str(migrations))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def _publish_new(source: Path, target: Path) -> None:
    """以同目录硬链接原子发布，目标存在或文件系统不支持时拒绝覆盖"""
    try:
        os.link(source, target)
    except FileExistsError as error:
        raise RuntimeError(f"迁移期间目标库已出现，拒绝覆盖：{target}") from error


def import_legacy_database(source: Path, target: Path, migrations: Path) -> bool:
    """首次导入旧 SQLite 库，失败保留原库且不留下半成品目标库"""
    if target.exists():
        with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if tables:
            _validate_existing(target)
            with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                names = {row[0] for row in tables}
                revisions = ({row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
                             if "alembic_version" in names else set())
            if not revisions or revisions.issubset(LEGACY_REVISIONS):
                return _upgrade_existing_legacy(target, migrations)
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
        _publish_new(temporary, target)
        return True
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(temporary) + suffix).unlink(missing_ok=True)


def _validate_existing(target: Path) -> None:
    with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("现有插件数据库完整性检查失败，拒绝覆盖")
        _counts(connection)


def _upgrade_existing_legacy(target: Path, migrations: Path) -> bool:
    """持有 SQLite 写锁直到升级提交，保留快照并先在副本校验"""
    token = uuid4().hex
    backup = target.with_name(f"{target.name}.legacy-{token}.bak")
    snapshot = target.with_name(f"{target.name}.snapshot-{token}.tmp")
    migrated = target.with_name(f"{target.name}.upgrade-{token}.tmp")
    deadline = monotonic() + 120

    def progress(status: int, remaining: int, total: int) -> None:
        if monotonic() > deadline:
            raise TimeoutError("同路径旧库迁移超过 120 秒，请停止其他数据库访问后重试")

    engine = create_engine(URL.create("sqlite", database=str(target)), connect_args={"timeout": 30})
    try:
        with engine.connect() as locked:
            locked.exec_driver_sql("BEGIN IMMEDIATE")
            # 等待锁期间另一迁移可能已完成，必须在锁内重新判定版本
            names = {row[0] for row in locked.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
            revisions = ({row[0] for row in locked.exec_driver_sql("SELECT version_num FROM alembic_version")}
                         if "alembic_version" in names else set())
            if revisions and not revisions.issubset(LEGACY_REVISIONS):
                return False
            with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(snapshot)) as copied:
                    source.backup(copied, pages=1024, progress=progress, sleep=0.05)
                    counts = _counts(copied)
            _validate_existing(snapshot)
            _publish_new(snapshot, backup)
            # 沿用普通导入的完整性、revision 和升级前后行数校验
            import_legacy_database(backup, migrated, migrations)
            _upgrade_locked(locked, migrations)
            if locked.exec_driver_sql("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("升级后的数据库完整性检查失败")
            if any(locked.exec_driver_sql(f'SELECT COUNT(*) FROM "{table}"').scalar() != count
                   for table, count in counts.items()):
                raise RuntimeError("旧库升级前后行数发生变化，拒绝继续迁移")
            locked.commit()
        return True
    except Exception as error:
        if backup.exists():
            raise RuntimeError(f"同路径旧库迁移失败：{error}；旧库快照保留：{backup}") from error
        raise
    finally:
        engine.dispose()
        # 完整旧库备份不清理，失败和成功均可供恢复
        for path in (snapshot, migrated):
            for suffix in ("", "-wal", "-shm", "-journal"):
                Path(str(path) + suffix).unlink(missing_ok=True)
