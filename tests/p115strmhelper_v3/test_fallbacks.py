"""V3 无 Rust 扩展路径的行为回归测试"""

import importlib.util
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper"


def load(name):
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "utils" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tree = load("txt_tree_fallback")
scan = load("share_scan_fallback")


def test_tree_preserves_physical_line_numbers_and_duplicates(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    tree.add_paths(left, ["/a", "", " /b ", "/b"])
    tree.add_paths(right, ["/a", ""])
    assert tree.count(left) == 3
    assert list(tree.compare_trees(left, right)) == ["/b", "/b"]
    assert list(tree.compare_trees_lines(left, right)) == [3, 4]
    assert tree.get_path_by_line_number(left, 2) == ""
    assert tree.get_path_by_line_number(left, 3) == "/b"
    assert tree.get_path_by_line_number(left, 0) is None
    assert tree.get_path_by_line_number(left, 5) is None


def test_tree_missing_append_overwrite_clear(tmp_path):
    path = tmp_path / "tree"
    assert tree.count(path) == 0
    assert tree.get_path_by_line_number(path, 1) is None
    with pytest.raises(FileNotFoundError):
        list(tree.compare_trees(path, tmp_path / "other"))
    tree.add_paths(path, ["a"])
    tree.add_paths(path, ["b"], append=True)
    assert list(tree.compare_trees(path, tmp_path / "missing")) == ["a", "b"]
    tree.add_paths(path, ["c"])
    assert tree.count(path) == 1
    tree.clear(path)
    tree.clear(path)
    assert not path.exists()


@pytest.mark.parametrize("line,expected", [
    ("http://mp/P115StrmHelper/redirect_url?share_code=a&receive_code=b", {("a", "b")}),
    ("fooP115StrmHelper?share_code=a%2Bb&receive_code=x+y#fragment", {("a+b", "x y")}),
    ("http://mp/P115StrmHelper?share_code=first&share_code=second&receive_code=b", {("first", "b")}),
    ("http://mp/P115StrmHelper?share_code=a&receive_code=", set()),
    ("http://mp/P115StrmHelper?share_code=&receive_code=b", set()),
    ("https://115.com/s/a?password=b", set()),
    ("http://mp/OtherPlugin?share_code=a&receive_code=b", set()),
])
def test_share_parser_matches_upstream_gate(line, expected):
    assert scan._pairs(line.encode()) == expected


def test_scan_cache_and_invalidation(tmp_path):
    content = b"\xef\xbb\xbfhttp://mp/P115StrmHelper?share_code=a&receive_code=b\n"
    path = tmp_path / "movie.STRM"
    path.write_bytes(content + content)
    (tmp_path / "invalid.strm").write_bytes(b"\xff\xfe")
    (tmp_path / "ignored.txt").write_bytes(content)
    cache = scan.ShareStrmScanCache()
    assert cache.scan(tmp_path) == [("a", "b")]
    assert cache.paths_for_many(tmp_path, [("a", "b"), ("absent", "x")]) == {
        ("a", "b"): [str(path)], ("absent", "x"): []}
    path.unlink()
    assert cache.scan(tmp_path) == [("a", "b")]
    cache.invalidate(tmp_path)
    assert cache.scan(tmp_path) == []


def test_scan_read_limit_and_invalid_worker_count(tmp_path):
    (tmp_path / "movie.strm").write_text("x" * 100 + "\nhttp://mp/P115StrmHelper?share_code=a&receive_code=b")
    cache = scan.ShareStrmScanCache()
    assert cache.scan(tmp_path, max_file_bytes=100) == []
    with pytest.raises(ValueError):
        cache.scan(tmp_path, num_threads=0)
