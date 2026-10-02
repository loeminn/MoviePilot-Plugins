# 115 STRM 助手 — MoviePilot V3

本仓库仅维护 **115 网盘 STRM 助手的 MoviePilot V3 适配版**，基于 [DDSRem-Dev/MoviePilot-Plugins](https://github.com/DDSRem-Dev/MoviePilot-Plugins) 原版开发，保留原作者署名及许可证。

当前版本 **3.0.0 候选版**，目标宿主 **MoviePilot >=3.1.0**。尚未完成真实 MP V3 / 115 账号联调，`release: false`，未发布正式发行版。

- 使用 MP 原生整理，禁用旧版批量整理接管；保留“监控 MP 整理生成 STRM”
- 保留 302、全量/增量同步、分享等原有功能；302 核心逻辑保持原版
- 错误、分享链接、离线链接三项上报默认关闭，已有明确配置保留
- 不包含 V2 插件和其他插件

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
python -m pip install pytest 'pydantic>=2,<3'
python -m pytest tests/p115strmhelper_v3 -q
python -m unittest discover -s plugins.v3/p115strmhelper/tests -p test_r302_concurrency.py -q
```

前端在 `frontend/p115strmhelper` 中运行 `npm ci`，设置 `MP_PLUGIN_V3=1` 后运行 `npm run build`。发布工作流会自动构建前端并打包。

本地已有 19 项适配测试和 6 项 302 并发测试通过。它们使用宿主、数据库和网络边界替身，不等于真实宿主端到端验证。

仓库精简通过普通提交完成，上游历史保留，方便溯源和后续同步。
