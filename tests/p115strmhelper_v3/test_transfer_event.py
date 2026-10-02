"""执行真实 STRM 处理方法，网盘、数据库和宿主服务使用边界替身"""

import ast
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper"


@pytest.mark.parametrize("storage", ["u115", "115网盘Plus"])
def test_native_transfer_event_writes_strm(tmp_path, storage):
    tree = ast.parse((PLUGIN / "helper/strm/transfer.py").read_text("utf8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef)
                and n.name in {"generate_strm_files", "do_generate"}]
    config = SimpleNamespace(transfer_monitor_clouddrive2_enabled=False,
                             transfer_monitor_emby_mediainfo_enabled=False,
                             get_config=lambda key: False)
    path_utils = SimpleNamespace(
        get_media_path=lambda *args: (True, str(tmp_path), "/Movies"),
        has_prefix=lambda path, prefix: path.startswith(prefix + "/"),
        sanitize_path_parts=lambda path: path,
    )
    expected = "http://localhost:3000/api/v1/plugin/P115StrmHelper/redirect?pickcode=12345678901234567"
    namespace = dict(Path=Path, PurePosixPath=PurePosixPath, configer=config,
                     logger=MagicMock(), sentry_manager=MagicMock(),
                     FileDbHelper=MagicMock(), StrmUrlGetter=lambda: SimpleNamespace(get_strm_url=lambda *a: expected),
                     PathUtils=path_utils, StorageChain=lambda: SimpleNamespace(is_bluray_folder=lambda item: False),
                     StrmGenerater=SimpleNamespace(get_strm_filename=lambda name: name.with_suffix(".strm")),
                     EventType=SimpleNamespace(TransferComplete="video", AudioTransferComplete="audio", SubTitleTransferComplete="subtitle", SubtitleTransferComplete="subtitle"),
                     settings=SimpleNamespace(RMT_MEDIAEXT=[".mkv"], RMT_SUBEXT=[".srt"], RMT_AUDIOEXT=[".flac"]))
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "transfer-methods", "exec"), namespace)
    helper = namespace["TransferStrmHelper"]()
    helper._get_overwrite_mode = lambda **kwargs: "always"
    file = SimpleNamespace(storage=storage, path="/Movies/Example/movie.mkv", name="movie.mkv", pickcode="12345678901234567")
    transfer = SimpleNamespace(target_item=file, target_diritem=SimpleNamespace(path="/Movies/Example"), transfer_type="copy")
    helper.do_generate(None, {"transferinfo": transfer, "meta": None, "mediainfo": None}, "video", None)
    assert (tmp_path / "Example/movie.strm").read_text("utf8") == expected
