"""为宿主管理数据库准备大整数网盘标识及原子导入状态"""

from alembic import op
import sqlalchemy as sa

revision = "p115_hostdb_310"
down_revision = "c76c9a1f52dc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """扩展 PostgreSQL 网盘标识范围并建立迁移状态表"""
    if op.get_bind().dialect.name == "postgresql":
        for table in ("files", "folders", "life_event", "open_files", "open_folders"):
            columns = ["id", "parent_id"]
            if table == "life_event":
                columns.append("file_id")
            for name in columns:
                op.alter_column(table, name, existing_type=sa.Integer(), type_=sa.BigInteger())
    op.create_table(
        "p115_legacy_import",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """拒绝自动回退，避免大整数及迁移状态丢失"""
    raise RuntimeError("宿主管理数据库不支持自动降级，请从备份恢复")
