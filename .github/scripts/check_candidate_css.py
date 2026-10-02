"""候选版复用官方 CSS 检查，仅豁免尚未发布的清单标志"""

from pathlib import Path

from check_federation_css import check_repository


def main() -> int:
    """检查全部 CSS 规则，不将候选版误设为自动发布"""
    root = Path(__file__).resolve().parents[2]
    release_only = "package.v3.json: 联邦插件 P115StrmHelper 必须设置 release=true"
    errors = check_repository(root)
    failures = [error for error in errors if error != release_only]
    for error in failures:
        print(error)
    if release_only in errors:
        print("候选版保留 release=false；正式发布前仍需通过完整官方检查")
    if not failures:
        print("CSS 检查通过")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
