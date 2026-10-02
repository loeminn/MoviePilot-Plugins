"""与上游 txt_tree_storage 文件格式一致的纯 Python 后端"""

from pathlib import Path
from typing import Iterable, Iterator, Optional


def add_paths(file_path: Path, paths: Iterable[str], append: bool = False) -> None:
    """按原始顺序写入路径，保留空行以维持物理行号"""
    with Path(file_path).open("a" if append else "w", encoding="utf-8") as stream:
        for path in paths:
            stream.write(path + "\n")


def _lines(file_path: Path) -> Iterator[str]:
    with Path(file_path).open(encoding="utf-8") as stream:
        for line in stream:
            yield line.strip()


def _other_paths(file_path: Path) -> set:
    try:
        return set(_lines(file_path))
    except FileNotFoundError:
        return set()


def compare_trees(file_path: Path, other_path: Path) -> Iterator[str]:
    """逐行返回另一目录树未包含的路径，保留重复项"""
    other = _other_paths(other_path)
    for path in _lines(file_path):
        if path not in other:
            yield path


def compare_trees_lines(file_path: Path, other_path: Path) -> Iterator[int]:
    """返回差异项的原文件物理行号，从一开始"""
    other = _other_paths(other_path)
    for number, path in enumerate(_lines(file_path), 1):
        if path not in other:
            yield number


def get_path_by_line_number(file_path: Path, line_number: int) -> Optional[str]:
    """按物理行号读取路径，文件或行不存在时返回 None"""
    if line_number <= 0:
        return None
    try:
        for number, path in enumerate(_lines(file_path), 1):
            if number == line_number:
                return path
    except FileNotFoundError:
        pass
    return None


def count(file_path: Path) -> int:
    """统计非空路径数，文件不存在时返回零"""
    try:
        return sum(bool(path) for path in _lines(file_path))
    except FileNotFoundError:
        return 0


def clear(file_path: Path) -> None:
    """删除目录树文件，与 Rust 后端保持相同语义"""
    Path(file_path).unlink(missing_ok=True)
