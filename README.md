# 115 STRM 助手 — MoviePilot V3

本仓库仅维护 **115 网盘 STRM 助手的 MoviePilot V3 适配版**，基于 [DDSRem-Dev/MoviePilot-Plugins](https://github.com/DDSRem-Dev/MoviePilot-Plugins) 原版开发，保留原作者署名及许可证。

当前版本 **3.0.1**，目标宿主 **MoviePilot >=3.1.0**。[下载发行版](https://github.com/loeminn/MoviePilot-Plugins/releases/tag/P115StrmHelper_v3.0.1)。尚未完成真实 MP V3 / 115 账号端到端联调。

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

## 验证与构建

```sh
python -m pip install pytest 'pydantic>=2,<3' 'httpx[http2]~=0.28.1' orjson
python -m pytest tests/p115strmhelper_v3 -q
python -m unittest discover -s plugins.v3/p115strmhelper/tests -p test_r302_concurrency.py -q
```

前端在 `frontend/p115strmhelper` 中运行 `npm ci`，设置 `MP_PLUGIN_V3=1` 后运行 `npm run build`。发布工作流会自动构建前端并打包。

本地已有 28 项适配测试和 6 项 302 并发测试通过。运行适配测试前，将 `MOVIEPILOT_SOURCE` 环境变量设为 MoviePilot 源码目录，可执行其中两项真实宿主调度方法测试；未设置时这两项会跳过。CI 固定检出已核对的宿主提交并执行全部测试。测试使用数据库和网络边界替身，不等于真实宿主端到端验证。

配置持久化使用插件基类接口，历史查询使用公开 Oper；保存后重新初始化、模糊匹配及分身拒绝行为已有回归测试。

CSS 检查器来自 [官方仓库](https://github.com/jxxghp/MoviePilot-Plugins/blob/main/.github/scripts/check_federation_css.py)，保留原始检查规则。发布版本 CI 和发布工作流均运行完整 `check_federation_css.py`；`check_candidate_css.py` 仅供未来未发布候选版本使用。本次已移除 Vuetify 全局基础样式产物。

仓库精简通过普通提交完成，上游历史保留，方便溯源和后续同步。
