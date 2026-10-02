"""按上游分享 STRM 查询规则提供无原生扩展的扫描后端"""

from os import walk
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import parse_qsl

Pair = Tuple[str, str]
RootKey = Union[str, Path]


def _pairs(content: bytes) -> set:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return set()
    pairs = set()
    for line in text.splitlines():
        if not all(key in line for key in ("P115StrmHelper", "share_code=", "receive_code=")):
            continue
        if "?" not in line:
            continue
        query = line.strip().split("?", 1)[1].split("#", 1)[0]
        values = {}
        for key, value in parse_qsl(query, keep_blank_values=True):
            values.setdefault(key, value)
        share = values.get("share_code", "")
        receive = values.get("receive_code", "")
        if share and receive:
            pairs.add((share, receive))
    return pairs


class ShareStrmScanCache:
    """缓存每个扫描根目录的分享码与 STRM 路径索引"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._by_root: Dict[str, Tuple[List[Pair], Dict[Pair, List[str]]]] = {}

    def _ensure_index(self, root: RootKey, max_file_bytes: int = 262_144,
                      num_threads: Optional[int] = None):
        if num_threads is not None and num_threads < 1:
            raise ValueError("num_threads must be >= 1")
        key = str(Path(root).resolve())
        with self._lock:
            if key in self._by_root:
                return self._by_root[key]
        index: Dict[Pair, List[str]] = {}
        for directory, _, names in walk(key, followlinks=False):
            for name in names:
                path = Path(directory) / name
                if path.suffix.lower() != ".strm" or path.is_symlink():
                    continue
                try:
                    with path.open("rb") as stream:
                        content = stream.read(max_file_bytes)
                    for pair in _pairs(content):
                        index.setdefault(pair, []).append(str(path))
                except OSError:
                    continue
        index = {pair: sorted(set(paths)) for pair, paths in index.items()}
        result = (sorted(index), index)
        with self._lock:
            return self._by_root.setdefault(key, result)

    def scan(self, root: RootKey, max_file_bytes: int = 262_144,
             num_threads: Optional[int] = None) -> List[Pair]:
        """返回根目录中去重并排序的分享码与提取码组合"""
        pairs, _ = self._ensure_index(root, max_file_bytes, num_threads)
        return list(pairs)

    def paths_for_many(self, root: RootKey, pairs: Sequence[Pair],
                       max_file_bytes: int = 262_144,
                       num_threads: Optional[int] = None) -> Dict[Pair, List[str]]:
        """查询指定组合对应的 STRM 文件路径"""
        _, index = self._ensure_index(root, max_file_bytes, num_threads)
        return {pair: list(index.get(pair, [])) for pair in pairs}

    def invalidate(self, root: Optional[RootKey] = None) -> None:
        """清除指定目录或全部缓存"""
        with self._lock:
            if root is None:
                self._by_root.clear()
            else:
                self._by_root.pop(str(Path(root).resolve()), None)
