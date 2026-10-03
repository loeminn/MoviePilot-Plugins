"""使用真实 SQLite、Alembic 和可选 PostgreSQL 验证旧库迁移"""

import importlib.util
import ast
from copy import deepcopy
import os
from pathlib import Path
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock
from threading import RLock

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy import Column, BigInteger, Text

PLUGIN = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper"
MIGRATIONS = PLUGIN / "database/migrations"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch):
    package = ModuleType("_p115_db_tests")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package.__name__, package)
    loaded = []
    for name, path in [("legacy_migration", "core/legacy_migration.py"),
                       ("postgres_import", "core/postgres_import.py"),
                       ("replace", "db_manager/replace.py")]:
        key = f"{package.__name__}.{name}"
        monkeypatch.setitem(sys.modules, key, None)
        loaded.append(load(key, PLUGIN / path))
    return SimpleNamespace(legacy=loaded[0], postgres=loaded[1], replace=loaded[2])


def old_database(path):
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "c76c9a1f52dc")
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO files(id,parent_id,name,path,extra) VALUES(9000000000001,0,'电影','/a','opaque')")
        db.execute("INSERT INTO folders(id,parent_id,name,path) VALUES(9000000000002,0,'目录','/folder')")
        db.execute("INSERT INTO life_event(id,type,file_id,parent_id,file_category,file_type) VALUES(9000000000003,1,9000000000001,0,1,1)")
        db.execute("INSERT INTO open_files(id,parent_id,path) VALUES(9000000000004,0,'/open')")
        db.execute("INSERT INTO open_folders(id,parent_id,path) VALUES(9000000000005,0,'/openfolder')")
    db.close()


def test_sqlite_import_preserves_rows_and_original(modules, tmp_path):
    source, target = tmp_path / "old.db", tmp_path / "new.db"
    old_database(source)
    original = source.read_bytes()
    assert modules.legacy.import_legacy_database(source, target, MIGRATIONS)
    assert source.read_bytes() == original
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT name,extra FROM files").fetchone() == ("电影", "opaque")
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("p115_hostdb_310",)
        assert all(db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] == 1 for t in modules.legacy.TABLES)
    db.close()
    assert not modules.legacy.import_legacy_database(source, target, MIGRATIONS)


def test_sqlite_snapshot_includes_committed_wal(modules, tmp_path):
    source, target = tmp_path / "old.db", tmp_path / "new.db"
    old_database(source)
    db = sqlite3.connect(source)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("INSERT INTO files(id,parent_id,path) VALUES(99,0,'/wal')")
        db.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        assert modules.legacy.import_legacy_database(source, target, MIGRATIONS)
        with sqlite3.connect(target) as copied:
            assert copied.execute("SELECT path FROM files WHERE id=99").fetchone() == ("/wal",)
        copied.close()
    finally:
        db.close()


@pytest.mark.parametrize("kind", ["corrupt", "foreign", "future"])
def test_bad_old_database_never_publishes_target(modules, tmp_path, kind):
    source, target = tmp_path / "old.db", tmp_path / "new.db"
    if kind == "corrupt":
        source.write_bytes(b"not a database")
    elif kind == "foreign":
        db = sqlite3.connect(source)
        db.execute("CREATE TABLE unrelated(id INTEGER)")
        db.close()
    else:
        old_database(source)
        with sqlite3.connect(source) as db:
            db.execute("UPDATE alembic_version SET version_num='future_revision'")
        db.close()
    original = source.read_bytes()
    with pytest.raises(Exception):
        modules.legacy.import_legacy_database(source, target, MIGRATIONS)
    assert not target.exists()
    assert source.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_interrupted_import_can_retry(modules, tmp_path, monkeypatch):
    source, target = tmp_path / "old.db", tmp_path / "new.db"
    old_database(source)
    upgrade = modules.legacy._upgrade_copy
    def fail(*args):
        raise RuntimeError("模拟迁移失败")
    monkeypatch.setattr(modules.legacy, "_upgrade_copy", fail)
    with pytest.raises(RuntimeError):
        modules.legacy.import_legacy_database(source, target, MIGRATIONS)
    assert not target.exists()
    monkeypatch.setattr(modules.legacy, "_upgrade_copy", upgrade)
    assert modules.legacy.import_legacy_database(source, target, MIGRATIONS)


def test_existing_empty_target_is_not_silently_accepted(modules, tmp_path):
    source, target = tmp_path / "old.db", tmp_path / "new.db"
    old_database(source)
    target.touch()
    with pytest.raises(RuntimeError, match="目标数据库为空"):
        modules.legacy.import_legacy_database(source, target, MIGRATIONS)


@pytest.fixture
def postgres():
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL required for real PostgreSQL integration")
    root = create_engine(url)
    schema = f"p115_test_{uuid4().hex}"
    with root.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = root.execution_options(schema_translate_map={None: schema})
    @event.listens_for(engine, "begin")
    def scope(connection):
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
    try:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield SimpleNamespace(engine=engine, schema=schema)
    finally:
        with root.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


def test_postgres_import_is_complete_idempotent_and_isolated(modules, postgres, tmp_path):
    source = tmp_path / "old.db"
    old_database(source)
    original = source.read_bytes()
    assert modules.postgres.import_postgres_database(postgres, source, MIGRATIONS, tmp_path)
    assert not modules.postgres.import_postgres_database(postgres, source, MIGRATIONS, tmp_path)
    with postgres.engine.connect() as db:
        assert db.execute(text("SELECT id,name,extra FROM files")).one() == (9000000000001, "电影", "opaque")
        assert all(db.scalar(text(f'SELECT COUNT(*) FROM "{t}"')) == 1 for t in modules.legacy.TABLES)
        assert db.scalar(text("SELECT status FROM p115_legacy_import")) == "imported"
        assert db.scalar(text("SELECT current_schema()")) == postgres.schema
    assert source.read_bytes() == original
    assert not list(tmp_path.glob("legacy-import-*"))


def test_postgres_failed_import_rolls_back_and_retries(modules, postgres, tmp_path):
    source = tmp_path / "old.db"
    old_database(source)
    with postgres.engine.begin() as db:
        db.execute(text("ALTER TABLE life_event ADD CONSTRAINT reject_import CHECK (id < 0)"))
    with pytest.raises(Exception):
        modules.postgres.import_postgres_database(postgres, source, MIGRATIONS, tmp_path)
    with postgres.engine.begin() as db:
        assert db.scalar(text("SELECT COUNT(*) FROM files")) == 0
        assert db.scalar(text("SELECT COUNT(*) FROM p115_legacy_import")) == 0
        db.execute(text("ALTER TABLE life_event DROP CONSTRAINT reject_import"))
    assert modules.postgres.import_postgres_database(postgres, source, MIGRATIONS, tmp_path)


def test_postgres_refuses_nonempty_unmarked_target(modules, postgres, tmp_path):
    source = tmp_path / "old.db"
    old_database(source)
    with postgres.engine.begin() as db:
        db.execute(text("INSERT INTO files(id,parent_id,path) VALUES(1,0,'/keep')"))
    with pytest.raises(RuntimeError, match="已有数据"):
        modules.postgres.import_postgres_database(postgres, source, MIGRATIONS, tmp_path)
    with postgres.engine.connect() as db:
        assert db.scalar(text("SELECT path FROM files")) == "/keep"


def test_postgres_missing_custom_source_requires_attention(modules, postgres, tmp_path):
    source = tmp_path / "missing.db"
    with pytest.raises(RuntimeError, match="旧库路径不存在"):
        modules.postgres.import_postgres_database(postgres, source, MIGRATIONS, tmp_path)
    assert not modules.postgres.import_postgres_database(postgres, source, MIGRATIONS, tmp_path, allow_missing=True)
    with postgres.engine.connect() as db:
        assert db.scalar(text("SELECT status FROM p115_legacy_import")) == "fresh"


def test_postgres_replace_matches_sqlite_for_both_unique_keys(modules, postgres):
    class Base(DeclarativeBase):
        pass
    class File(Base):
        __tablename__ = "files"
        id = Column(BigInteger, primary_key=True)
        parent_id = Column(BigInteger)
        path = Column(Text, unique=True)
        name = Column(Text)
    batches = [
        [{"id": 1, "parent_id": 0, "path": "/a"}, {"id": 2, "parent_id": 0, "path": "/b"}],
        [{"id": 3, "parent_id": 0, "path": "/a"}, {"id": 3, "parent_id": 0, "path": "/b"},
         {"id": 4, "parent_id": 0, "path": "/b"}, {"id": 3, "parent_id": 0, "path": None}],
        [{"id": "03", "parent_id": 0, "path": "/first"},
         {"id": 3, "parent_id": 0, "path": "/second"},
         {"id": "  +3  ", "parent_id": 0, "path": "/last"}],
    ]
    original = deepcopy(batches)
    sqlite = create_engine("sqlite://")
    Base.metadata.create_all(sqlite)
    results = []
    try:
        for engine in (sqlite, postgres.engine):
            with Session(engine) as db:
                for batch in batches:
                    modules.replace.replace_batch(db, File, batch)
                    db.commit()
                results.append(db.execute(text("SELECT id,path FROM files ORDER BY id")).all())
        assert results[0] == results[1] == [(3, "/last"), (4, "/b")]
        assert batches == original
    finally:
        sqlite.dispose()


@pytest.mark.parametrize("key", [None, True, 1.5, "1.5", "bad", 2**63, -(2**63)-1])
def test_postgres_invalid_id_fails_before_database_changes(modules, key):
    db = Mock()
    db.get_bind.return_value.dialect.name = "postgresql"
    with pytest.raises(ValueError, match="64 位整数"):
        modules.replace.replace_batch(db, Mock(), [{"id": 1}, {"id": key}])
    db.execute.assert_not_called()


@pytest.fixture
def real_models(monkeypatch):
    host = os.environ.get("MOVIEPILOT_SOURCE")
    if not host:
        pytest.skip("MOVIEPILOT_SOURCE required for actual plugin model base")
    import runpy
    factory = runpy.run_path(str(Path(host) / "app/db/plugin/base.py"))["plugin_declarative_base"]
    database = ModuleType("app.sdk.database")
    database.PluginDatabaseHandle = object
    database.plugin_declarative_base = factory
    logging = ModuleType("app.sdk.logging")
    logging.logger = Mock()
    monkeypatch.setitem(sys.modules, "app.sdk.database", database)
    monkeypatch.setitem(sys.modules, "app.sdk.logging", logging)
    package = ModuleType("_p115_model_tests")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package.__name__, package)
    before = set(sys.modules)
    try:
        manager = load("_p115_model_tests.db_manager", PLUGIN / "db_manager/__init__.py")
        models = load("_p115_model_tests.db_manager.models", PLUGIN / "db_manager/models/__init__.py")
        yield manager, models
    finally:
        for key in set(sys.modules) - before:
            if key.startswith("_p115_model_tests."):
                del sys.modules[key]


def test_actual_models_load_and_owned_sessions_commit_or_rollback(real_models):
    manager, models = real_models
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite://")
    manager.P115StrmHelperBase.metadata.create_all(engine)
    manager.bind_handle(SimpleNamespace(session=sessionmaker(bind=engine)))
    try:
        models.File.upsert_batch_by_list(None, [{"id": 1, "parent_id": 0, "path": "/ok"}])
        assert models.File.get_by_id(None, 1).path == "/ok"
        @manager.db_update
        def fail(db):
            db.execute(text("INSERT INTO files(id,parent_id,path) VALUES(2,0,'/rollback')"))
            raise RuntimeError("rollback")
        with pytest.raises(RuntimeError, match="rollback"):
            fail(None)
        assert models.File.get_by_id(None, 2) is None
        assert len(manager.P115StrmHelperBase.metadata.tables) == 5
    finally:
        engine.dispose()


@pytest.mark.parametrize("model_name", ["File", "Folder", "LifeEvent", "OpenFile", "OpenFolder"])
def test_actual_postgres_models_write_large_ids(real_models, postgres, model_name):
    manager, models = real_models
    from sqlalchemy.orm import sessionmaker
    manager.bind_handle(SimpleNamespace(session=sessionmaker(bind=postgres.engine)))
    model = getattr(models, model_name)
    row = {"id": 9000000000001, "parent_id": 9000000000002}
    if model_name == "LifeEvent":
        row.update(file_id=9000000000003, type=1, file_category=1, file_type=1)
    else:
        row.update(path="/large", name="large")
    last = {**row, "id": str(row["id"]), "parent_id": 9000000000004}
    batch = [row, last]
    original = deepcopy(batch)
    model.upsert_batch_by_list(None, batch)
    assert batch == original
    item = model.get(None, 9000000000001)
    assert item.parent_id == 9000000000004
    if model_name == "LifeEvent":
        assert item.file_id == 9000000000003
    else:
        assert item.path == "/large"


@pytest.mark.parametrize("fail_import", [False, True])
def test_prepare_binds_only_after_postgres_import(tmp_path, fail_import):
    source = tmp_path / "legacy.db"
    calls = []
    handle = SimpleNamespace(schema="plugin_test")
    class Plugin:
        def get_database_migrations(self):
            return MIGRATIONS

        def get_data_path(self):
            return tmp_path

        def get_database(self):
            calls.append("handle")
            return handle

    def importing(*args, **kwargs):
        calls.append("import")
        if fail_import:
            raise RuntimeError("import failed")
        return True

    namespace = dict(
        Any=object, Dict=dict, Path=Path, _prepare_lock=RLock(),
        settings=SimpleNamespace(DB_TYPE="postgresql"), logger=Mock(),
        ConfigManager=SimpleNamespace(_get_default_plugin_db_path=lambda: source),
        ensure_database=lambda *args, **kwargs: calls.append("ensure"),
        import_postgres_database=importing,
        bind_handle=lambda value: calls.append("bind"),
    )
    tree = ast.parse((PLUGIN / "core/database.py").read_text("utf8"))
    method = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "prepare_database")
    exec(compile(ast.Module(body=[method], type_ignores=[]), "prepare-database", "exec"), namespace)
    if fail_import:
        with pytest.raises(RuntimeError, match="import failed"):
            namespace["prepare_database"](Plugin(), {"PLUGIN_DB_PATH": str(source)})
        assert calls == ["ensure", "handle", "import"]
    else:
        namespace["prepare_database"](Plugin(), {"PLUGIN_DB_PATH": str(source)})
        assert calls == ["ensure", "handle", "import", "bind"]
