# 3.1.0 宿主管理数据库

插件的文件、目录、生活事件等五张业务表改由 MP V3 的插件数据库框架管理。
仍只支持单实例，使用 MP 原生整理；三项上报的默认值不变。

## 数据放在哪里

- SQLite 宿主：`self.get_data_path()/plugin.db`
- PostgreSQL 宿主：MP 按插件 ID 分配的独立 schema，复用宿主数据库连接配置
- 插件配置和小型结构化数据继续通过插件基类接口保存

`PLUGIN_DB_PATH` 只用于定位待导入的旧 SQLite 数据库，不再决定新库的位置。
旧的 `DB_WAL_ENABLE`、`PLUGIN_DATABASE_SCRIPT_LOCATION` 和
`PLUGIN_DATABASE_VERSION_LOCATIONS` 为配置兼容而保留，新数据库不再读取它们。

## 首次升级

1. 升级前备份 MP 配置目录及 PostgreSQL 数据库，确认 `PLUGIN_DB_PATH` 指向实际旧库
2. 首次初始化先停止插件后台服务，数据库准备完成后才启动业务服务
3. 使用 SQLite backup API 生成一致性快照，包含 WAL 中已经提交的数据，不修改或删除旧库
4. 在临时快照上执行 Alembic 升级，检查完整性和五张业务表升级前后的行数
5. SQLite 校验成功后原子落盘；PostgreSQL 在一个事务内导入全部表和完成标记，失败整体回滚

PostgreSQL 使用 `p115_legacy_import` 表记录完成状态，标记和数据在同一事务提交；
已有完成标记时不会重复导入。若插件数据目录已有宿主管理的 `plugin.db`，优先从该库导入，
避免使用更早的遗留库。导入完成后再次启动不会用旧库覆盖新数据。

默认旧库不存在时按全新安装处理；自定义旧库路径不存在时拒绝首次初始化。
已有 SQLite 目标为空、损坏，或 PostgreSQL 业务表非空却没有完成标记时，会停止而不覆盖。
损坏库、未知迁移版本、升级造成行数变化或数据库权限不足也会中止加载。

## 恢复与后续备份

迁移失败后原库仍在，可修复原因后重新加载。不要通过删除有数据的目标库来绕过报错。
临时副本只用于本次导入，结束后清理；旧库文件保留，但升级后的新增数据只写新库。

升级成功并产生新数据后，不能仅安装 3.0.6 就认为已完成数据回滚：旧版本读取旧 SQLite 文件，
它不含升级后的变更。回退需要恢复对应时间点的备份，或进行明确的数据导出迁移。
PostgreSQL 日常备份应包含插件 schema，不应只备份 `/config` 目录。

## 接口与验证边界

使用 `get_database()`、`get_database_migrations()` 以及
`app.sdk.database.plugin_declarative_base()`。
宿主通常在 `init_plugin()` 返回后执行迁移，但本插件初始化会启动业务线程，因此先调用
已核对的 `app.db.plugin.registry.ensure_database()` 完成同一准备流程；这个入口不是 SDK 导出，
后续宿主升级须复核。连接池释放交给宿主，插件只关闭自己取得的独立会话。

五张表的批量写入兼容 SQLite 与 PostgreSQL，保留按 ID 或唯一路径替换语义。
PostgreSQL 使用 64 位网盘标识；写入在表级事务锁内完成，避免不同唯一键产生并发替换冲突。
大量写入期间同表其他写入会等待，读取仍可继续。

CI 使用 PostgreSQL 16 与 Python 3.14，测试旧库导入、失败回滚与重试、完成标记、schema 隔离、
大整数业务读写、SQLite WAL 和副本校验。网络与宿主组合边界有替身，不能替代真实 MP/115
账号端到端联调。SQLite 与 PostgreSQL 双向在线切换不在本次支持范围内。
