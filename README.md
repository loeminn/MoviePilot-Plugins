# 115 STRM 助手 — MoviePilot V3

本仓库仅维护 **115 网盘 STRM 助手的 MoviePilot V3 适配版**，基于 [DDSRem-Dev/MoviePilot-Plugins](https://github.com/DDSRem-Dev/MoviePilot-Plugins) 原版开发，保留原作者署名及许可证。

当前版本 **3.1.1**，目标宿主 **MoviePilot >=3.1.0**。[下载发行版](https://github.com/loeminn/MoviePilot-Plugins/releases/tag/P115StrmHelper_v3.1.1)。尚未完成真实 MP V3 / 115 账号端到端联调。

- 使用 MP 原生整理，禁用旧版批量整理接管；保留“监控 MP 整理生成 STRM”
- 保留 302、全量/增量同步、分享等原有功能；302 核心逻辑保持原版
- 错误、分享链接、离线链接三项上报默认关闭，已有明确配置保留
- 不包含 V2 插件和其他插件
- 当前仅支持单实例，创建虚拟分身时会拒绝初始化，避免共享配置、缓存和端口

## 目录

| 路径 | 内容 |
| --- | --- |
| `plugins.v3/p115strmhelper/` | 插件源码、前端产物、依赖和 Rust 源码 |
| `frontend/p115strmhelper/` | 前端源码 |
| `tests/p115strmhelper_v3/` | V3 适配测试 |
| `docs/p115strmhelper/` | 上游功能文档，以 V3 适配说明为准 |
| `package.v3.json` | 仅包含 P115StrmHelper 的插件清单 |

[V3 适配说明](plugins.v3/p115strmhelper/README.md) · [上游使用文档](docs/p115strmhelper/README.md)

3.1.1 新增离线下载进度检查开关，可在「网盘管理 → 网盘整理 → 离线下载」中关闭，保存后停止每两分钟轮询。开关默认开启以保留原有行为；关闭后也不再通过该检查触发离线完成后的整理，手动查询任务列表不受影响。

3.1.0 汇总宿主管理数据库及全部后续修复，可从 3.0.6 直接升级。支持 SQLite 和 PostgreSQL，包含旧库备份与校验导入、迁移并发保护、批量 ID/路径替换、目录重命名事务及 Open 文件写入修复。升级前请阅读[数据库迁移与恢复说明](docs/p115strmhelper/DATABASE_V3.md)。

3.0.6 修复分享清理记录的媒体标识映射和 HDHive 浏览器通知权限脚本；新增 6 项媒体身份测试及 3 项实际浏览器脚本测试。

3.0.5 串行执行详情页自定义配置保存，避免并发更新互相覆盖；分享同步在保存失败时停止并显示错误。新增 2 项后端测试、3 项前端测试。

3.0.4 修复详情页保存配置后客户端和定时任务未刷新的问题；保存流程通过宿主管理器重新初始化并刷新服务、命令和路由。

3.0.3 修复配置页与分享配置页选择本地目录时的“无效响应”错误。更新后刷新浏览器页面。

3.0.2 修复 `concurrenttools 0.1.9` 导致的 `threadpool_map` 导入失败；更新后请重启 MoviePilot。兼容层和验证范围见 [V3 适配说明](plugins.v3/p115strmhelper/README.md)。

## 验证与构建

```sh
python -m pip install pytest 'pydantic>=2,<3' 'httpx[http2]~=0.28.1' orjson 'fastapi~=0.141.1' 'sqlalchemy>=2,<3' 'alembic>=1.16,<2' 'psycopg[binary]>=3,<4'
python -m pytest tests/p115strmhelper_v3 -q
python -m unittest discover -s plugins.v3/p115strmhelper/tests -p test_r302_concurrency.py -q
```

真实依赖测试另运行 `python -m pytest tests/dependencies -q`；先安装 `p115client==0.0.9.6.5.1`，并分别使用 `python-concurrenttools==0.1.8` 和 `==0.1.9`。CI 在 Python 3.14 上执行两组测试，每组 5 项，不使用 p115client 替身。

前端在 `frontend/p115strmhelper` 中运行 `npm ci`，设置 `MP_PLUGIN_V3=1` 后运行 `npm run build`。发布工作流会自动构建前端并打包。

适配测试共 86 项，其中 14 项使用真实 PostgreSQL；本地精简环境运行 72 项，其余 14 项在配置了 PostgreSQL 的 CI 中运行。另有 6 项 302 并发测试。运行适配测试前，将 `MOVIEPILOT_SOURCE` 环境变量设为 MoviePilot 源码目录，可执行其中两项真实宿主调度方法测试及一项动态路由注册测试；未设置时宿主相关测试会跳过。CI 固定检出已核对的宿主提交并执行全部测试。测试使用数据库和网络边界替身，不等于真实宿主端到端验证。

配置持久化使用插件基类接口，历史查询使用公开 Oper；保存后重新初始化、模糊匹配及分身拒绝行为已有回归测试。

整理分类测试已使用隔离的 V3 SDK 桩，单独运行且不依赖宿主安装：

```sh
python -m unittest discover -s plugins.v3/p115strmhelper/tests -p test_transfer_classify.py -q
```

其他原版测试包含需要宿主和完整依赖的模块。运行完整 `plugins.v3/p115strmhelper/tests` 时，应在本仓库根目录启动，将 `PYTHONPATH` 按顺序设为宿主根目录、插件目录，使用 `unittest discover`；不要在插件目录直接启动，以免插件 `version.py` 遮蔽宿主同名模块。分类测试恢复 `sys.modules`，不会将其假宿主模块留给其他用例。本地精简测试环境不代表完整宿主环境，不能据此声称原版全部测试通过。

上报开关默认关闭，升级保留已存储的显式值；实际部署若继承了 `true`，需要在设置中关闭。`python-concurrenttools` 仍只支持 `>=0.1.8,<0.1.10`，不对未验证版本扩大兼容范围。Sentry 2.x 的旧 Hub 接口暂仍可用，后续迁移需验证插件与宿主的上报隔离；`PluginManager` 经 SDK 导出，注册刷新函数仍是已核对的宿主内部接口。

CSS 检查器来自 [官方仓库](https://github.com/jxxghp/MoviePilot-Plugins/blob/main/.github/scripts/check_federation_css.py)，保留原始检查规则。发布版本 CI 和发布工作流均运行完整 `check_federation_css.py`；`check_candidate_css.py` 仅供未来未发布候选版本使用。本次已移除 Vuetify 全局基础样式产物。

仓库精简通过普通提交完成，上游历史保留，方便溯源和后续同步。
