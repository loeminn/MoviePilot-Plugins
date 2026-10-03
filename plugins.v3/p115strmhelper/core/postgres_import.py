"""将旧 SQLite 快照原子导入宿主管理的 PostgreSQL 插件 schema"""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import MetaData, Table, func, insert, select, text

from .legacy_migration import TABLES, import_legacy_database


def import_postgres_database(
    handle: Any, source: Path, migrations: Path, staging: Path, allow_missing: bool = False
) -> bool:
    """导入和完成标记在同一事务提交，失败可重试且保留旧库"""
    snapshot = staging / f"legacy-import-{uuid4().hex}.sqlite"
    try:
        with handle.engine.begin() as connection:
            connection.execute(text("LOCK TABLE p115_legacy_import IN EXCLUSIVE MODE"))
            metadata = MetaData()
            marker = Table("p115_legacy_import", metadata, autoload_with=connection)
            if connection.execute(select(marker.c.id).where(marker.c.id == 1)).first():
                return False
            tables = {name: Table(name, metadata, autoload_with=connection) for name in TABLES}
            if any(connection.scalar(select(func.count()).select_from(table)) for table in tables.values()):
                raise RuntimeError("PostgreSQL 插件库已有数据但没有导入标记，拒绝覆盖，请先核实来源")
            if not source.exists():
                if not allow_missing:
                    raise RuntimeError(f"自定义旧库路径不存在，拒绝以空库启动：{source}")
                connection.execute(insert(marker).values(id=1, status="fresh", source=str(source)))
                return False
            staging.mkdir(parents=True, exist_ok=True)
            import_legacy_database(source, snapshot, migrations)
            with closing(sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)) as old:
                old.row_factory = sqlite3.Row
                for name, table in tables.items():
                    cursor = old.execute(f'SELECT * FROM "{name}"')
                    copied = 0
                    while rows := cursor.fetchmany(1000):
                        connection.execute(insert(table), [dict(row) for row in rows])
                        copied += len(rows)
                    if connection.scalar(select(func.count()).select_from(table)) != copied:
                        raise RuntimeError(f"PostgreSQL 导入行数校验失败：{name}")
            connection.execute(insert(marker).values(id=1, status="imported", source=str(source)))
            return True
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(snapshot) + suffix).unlink(missing_ok=True)
