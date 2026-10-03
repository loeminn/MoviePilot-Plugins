"""跨数据库保留按主键或唯一路径替换的批量写入语义"""

import re
from typing import Any, Dict, List

from sqlalchemy import delete, insert, or_, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session


def replace_batch(db: Session, model: Any, batch: List[Dict]) -> None:
    """在调用方事务内替换记录，兼容同批次重复主键及路径"""
    if not batch:
        return
    if db.get_bind().dialect.name == "sqlite":
        db.execute(sqlite_insert(model).prefix_with("OR REPLACE"), batch)
        return
    if db.get_bind().dialect.name != "postgresql":
        raise RuntimeError("115 STRM 数据库仅支持 SQLite 和 PostgreSQL")
    # PostgreSQL 将数字字符串与整数视为同一主键，去重也必须使用相同类型
    normalized = []
    for row in batch:
        key = row["id"]
        if isinstance(key, str) and re.fullmatch(r"[+-]?[0-9]+", key.strip()):
            key = int(key)
        if type(key) is not int or not -(2**63) <= key < 2**63:
            raise ValueError("115 STRM 记录 id 必须是 64 位整数或整数字符串")
        normalized.append({**row, "id": key})
    batch = normalized
    table = model.__table__
    quoted = db.get_bind().dialect.identifier_preparer.quote(table.name)
    # 同时存在 id/path 两个唯一键，串行替换避免两个 upsert 在不同约束上互相冲突
    db.execute(text(f"LOCK TABLE {quoted} IN SHARE ROW EXCLUSIVE MODE"))
    rows = {}
    paths = {}
    has_path = "path" in table.c
    for row in batch:
        key = row["id"]
        prior = rows.pop(key, None)
        if prior is not None and has_path and prior.get("path") is not None:
            paths.pop(prior["path"], None)
        path = row.get("path") if has_path else None
        if path is not None:
            prior_id = paths.pop(path, None)
            if prior_id is not None:
                rows.pop(prior_id, None)
            paths[path] = key
        rows[key] = row
    for offset in range(0, len(batch), 1000):
        chunk = batch[offset:offset + 1000]
        criteria = [table.c.id.in_([row["id"] for row in chunk])]
        if has_path:
            criteria.append(table.c.path.in_([row["path"] for row in chunk if row.get("path") is not None]))
        db.execute(delete(table).where(or_(*criteria)))
    db.execute(insert(model), list(rows.values()))
