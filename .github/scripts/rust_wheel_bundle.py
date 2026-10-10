"""
生成和校验 Rust wheel 发布清单，源码统一按 LF 换行计算 SHA256
"""

import argparse
import hashlib
import json
import shutil
import tomllib
from pathlib import Path
from typing import Dict


EXTENSIONS = ("full_strm_sync", "share_strm_scan", "txt_tree_storage")
PLATFORMS = (
    "manylinux_x86_64", "manylinux_aarch64", "musllinux_x86_64",
    "musllinux_aarch64", "win_amd64", "macosx_x86_64",
    "macosx_arm64", "macosx_universal2",
)
NORMALIZATION = "CRLF-to-LF"


def source_hashes(plugin: Path) -> Dict[str, str]:
    """
    计算源码及构建配置的规范化校验和

    :param plugin (Path): 插件目录

    :return Dict: 相对路径与 SHA256
    """
    result = {}
    for extension in EXTENSIONS:
        root = plugin / "rust_utils" / extension
        paths = [root / name for name in ("Cargo.lock", "Cargo.toml", "pyproject.toml")]
        for directory, pattern in (("src", "*.rs"), ("python", "*.py"), ("tests", "*.py")):
            paths.extend((root / directory).rglob(pattern))
        for path in sorted(paths):
            data = path.read_bytes().replace(b"\r\n", b"\n")
            result[path.relative_to(plugin).as_posix()] = hashlib.sha256(data).hexdigest()
    return result


def wheel_hashes(plugin: Path, wheels: Path) -> Dict[str, str]:
    """
    验证三个扩展的版本及完整平台矩阵并计算二进制校验和

    :param plugin (Path): 插件目录
    :param wheels (Path): 构建产物目录

    :return Dict: wheel 文件名与 SHA256
    """
    versions = {
        name: tomllib.loads((plugin / "rust_utils" / name / "Cargo.toml").read_text("utf-8"))
        ["package"]["version"]
        for name in EXTENSIONS
    }
    expected = {(name, abi, platform) for name in EXTENSIONS
                for abi in ("cp312", "cp314") for platform in PLATFORMS}
    seen = set()
    result = {}
    for path in sorted(wheels.glob("*.whl")):
        name, version, python, abi, tags = path.stem.split("-")
        if name not in versions or version != versions[name] or python != abi:
            raise ValueError(f"wheel 名称、版本或 ABI 不匹配: {path.name}")
        platform = next((value for value in PLATFORMS if any(
            tag.startswith(value.split("_", 1)[0] + "_")
            and tag.endswith("_" + value.split("_", 1)[1])
            for tag in tags.split(".")
        )), None)
        key = (name, abi, platform)
        if key not in expected or key in seen:
            raise ValueError(f"wheel 平台缺失、重复或不支持: {path.name}")
        seen.add(key)
        result[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if seen != expected:
        raise ValueError(f"wheel 矩阵不完整，缺少: {sorted(expected - seen)}")
    return result


def main() -> None:
    """
    记录构建清单，或校验后将完整产物替换到发布目录
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("record", "install"))
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    metadata = {
        "schema_version": 2,
        "commit": args.commit,
        "source_hash_normalization": NORMALIZATION,
        "source_files_sha256": source_hashes(args.plugin),
        "wheels_sha256": wheel_hashes(args.plugin, args.wheels),
        "other_platforms_rebuilt": True,
    }
    record = args.wheels / "rust-build-info.json"
    if args.command == "record":
        record.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        return
    if json.loads(record.read_text("utf-8")) != metadata:
        raise ValueError("构建提交、源码或 wheel 校验和与发布清单不一致")
    destination = args.plugin / "wheels"
    if args.wheels.resolve() == destination.resolve():
        raise ValueError("构建产物目录不能与发布目录相同")
    destination.mkdir(parents=True, exist_ok=True)
    for extension in EXTENSIONS:
        for path in destination.glob(f"{extension}-*.whl"):
            path.unlink()
    for name in metadata["wheels_sha256"]:
        shutil.copy2(args.wheels / name, destination / name)
    shutil.copy2(record, destination / record.name)


if __name__ == "__main__":
    main()
