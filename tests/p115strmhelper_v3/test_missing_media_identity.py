"""使用宿主实际枚举验证缺失媒体记录的身份映射"""

import ast
import __future__
import os
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def identity_mapper():
    host = os.environ.get("MOVIEPILOT_SOURCE")
    if not host:
        pytest.skip("MOVIEPILOT_SOURCE required for actual MediaSource contract")
    tree = ast.parse((Path(host) / "app/schemas/types.py").read_text("utf8"))
    enum = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MediaSource")
    namespace = dict(Enum=Enum, Any=Any, Dict=Dict, uuid4=uuid4, time_unix=lambda: 123)
    exec(compile(ast.Module(body=[enum], type_ignores=[]), "host-media-source", "exec",
                 flags=__future__.annotations.compiler_flag), namespace)
    source = ROOT / "plugins.v3/p115strmhelper/helper/strm/share/cleaner.py"
    tree = ast.parse(source.read_text("utf8"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "row_from_transfer_history")
    method.decorator_list = []
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["row_from_transfer_history"], namespace["MediaSource"]


@pytest.mark.parametrize("source,key", [
    ("TMDB", "tmdbid"), ("Douban", "doubanid"), ("TVDB", "tvdbid"), ("IMDb", "imdbid"),
])
def test_source_maps_only_its_own_id(identity_mapper, source, key):
    mapper, media_source = identity_mapper
    member = getattr(media_source, source)
    for value in (member, member.value):
        history = SimpleNamespace(media_source=value, media_id="tt123", title="Example",
                                  tvdbid="stale-tvdb", imdbid="stale-imdb")
        row = mapper(history, "/media/a.strm", "share", "code")
        assert {k: row[k] for k in ("tmdbid", "doubanid", "tvdbid", "imdbid")} == {
            k: "tt123" if k == key else None for k in ("tmdbid", "doubanid", "tvdbid", "imdbid")
        }
        assert row["title"] == "Example"
        assert row["strm_path"] == "/media/a.strm"


@pytest.mark.parametrize("source", [None, "custom-source"])
def test_unknown_source_does_not_invent_legacy_ids(identity_mapper, source):
    mapper, _ = identity_mapper
    row = mapper(SimpleNamespace(media_source=source, media_id="123"), "/a.strm", "s", "c")
    assert all(row[k] is None for k in ("tmdbid", "doubanid", "tvdbid", "imdbid"))
