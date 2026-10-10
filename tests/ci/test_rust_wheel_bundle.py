"""
验证 Rust 发布产物完整性、来源校验及换行兼容性
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / ".github/scripts/rust_wheel_bundle.py"
SPEC = importlib.util.spec_from_file_location("rust_wheel_bundle", SCRIPT)
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class RustWheelBundleTests(unittest.TestCase):
    """
    使用隔离目录验证发布前检查和替换行为
    """

    def setUp(self) -> None:
        """
        创建三组扩展源码与完整 wheel 矩阵
        """
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plugin = self.root / "plugin"
        self.wheels = self.root / "artifacts"
        self.wheels.mkdir()
        tags = (
            "manylinux_2_17_x86_64.manylinux2014_x86_64",
            "manylinux_2_17_aarch64.manylinux2014_aarch64",
            "musllinux_1_2_x86_64", "musllinux_1_2_aarch64", "win_amd64",
            "macosx_10_12_x86_64", "macosx_11_0_arm64", "macosx_10_12_universal2",
        )
        for name in bundle.EXTENSIONS:
            root = self.plugin / "rust_utils" / name
            (root / "src").mkdir(parents=True)
            (root / "Cargo.toml").write_bytes(b'[package]\nversion = "1.0.0"\n')
            for relative in ("Cargo.lock", "pyproject.toml", "src/lib.rs"):
                (root / relative).write_bytes(b"first\nsecond\n")
            for abi in ("cp312", "cp314"):
                for tag in tags:
                    (self.wheels / f"{name}-1.0.0-{abi}-{abi}-{tag}.whl").write_bytes(b"wheel")
        destination = self.plugin / "wheels"
        destination.mkdir()
        self.old = destination / "full_strm_sync-0.1.0-cp312-cp312-win_amd64.whl"
        self.old.write_bytes(b"old")
        self.other = destination / "unrelated-1.0.0-py3-none-any.whl"
        self.other.write_bytes(b"keep")

    def _run(self, command: str, commit: str = "abc123") -> None:
        with patch("sys.argv", [str(SCRIPT), command, "--plugin", str(self.plugin),
                                "--wheels", str(self.wheels), "--commit", commit]):
            bundle.main()

    def test_line_endings_are_portable(self) -> None:
        """
        CRLF 与 LF 源码产生相同校验和
        """
        expected = bundle.source_hashes(self.plugin)
        for relative in expected:
            path = self.plugin / relative
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(expected, bundle.source_hashes(self.plugin))

    def test_complete_bundle_replaces_only_rust_wheels(self) -> None:
        """
        完整产物替换旧扩展并保留其他依赖
        """
        self._run("record")
        self._run("install")
        self.assertFalse(self.old.exists())
        self.assertEqual(self.other.read_bytes(), b"keep")
        destination = self.plugin / "wheels"
        self.assertEqual(len(list(destination.glob("*.whl"))), 49)
        metadata = json.loads((destination / "rust-build-info.json").read_text("utf-8"))
        self.assertEqual(metadata["source_hash_normalization"], "CRLF-to-LF")

    def test_missing_wheel_blocks_install(self) -> None:
        """
        缺少平台产物时不修改发布目录
        """
        self._run("record")
        next(self.wheels.glob("*.whl")).unlink()
        with self.assertRaises(ValueError):
            self._run("install")
        self.assertTrue(self.old.exists())

    def test_changed_wheel_blocks_install(self) -> None:
        """
        二进制校验失败时保留旧产物
        """
        self._run("record")
        next(self.wheels.glob("*.whl")).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self._run("install")
        self.assertTrue(self.old.exists())

    def test_changed_source_blocks_install(self) -> None:
        """
        不允许使用其他源码构建的产物
        """
        self._run("record")
        (self.plugin / "rust_utils/full_strm_sync/src/lib.rs").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self._run("install")
        self.assertTrue(self.old.exists())

    def test_wrong_commit_blocks_install(self) -> None:
        """
        不允许混入其他提交的构建产物
        """
        self._run("record")
        with self.assertRaises(ValueError):
            self._run("install", "different")
        self.assertTrue(self.old.exists())

    def test_duplicate_platform_is_rejected(self) -> None:
        """
        不允许同一扩展和 ABI 携带重复平台
        """
        duplicate = self.wheels / "full_strm_sync-1.0.0-cp312-cp312-macosx_11_0_x86_64.whl"
        duplicate.write_bytes(b"duplicate")
        with self.assertRaises(ValueError):
            self._run("record")

    def test_wrong_version_is_rejected(self) -> None:
        """
        wheel 版本必须与对应 Cargo 配置一致
        """
        path = next(self.wheels.glob("*.whl"))
        path.rename(path.with_name(path.name.replace("-1.0.0-", "-0.9.0-")))
        with self.assertRaises(ValueError):
            self._run("record")


if __name__ == "__main__":
    unittest.main()
