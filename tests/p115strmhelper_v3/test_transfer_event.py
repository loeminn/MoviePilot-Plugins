"""执行真实 STRM 处理方法，网盘、数据库和宿主服务使用边界替身"""

import ast
import os
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple
from unittest.mock import MagicMock
from zipfile import ZipFile

import pytest
from pydantic import BaseModel, Field

PLUGIN = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper"


def _transfer_environment(tmp_path: Path) -> Tuple[Any, Dict[str, Any], str]:
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
    return helper, namespace, expected


@pytest.mark.parametrize("storage", ["u115", "115网盘Plus"])
@pytest.mark.parametrize("fileid", ["123", None])
@pytest.mark.parametrize("resolved_id", [456, 0, None])
def test_native_transfer_event_writes_strm(
    tmp_path: Path, storage: str, fileid: Optional[str], resolved_id: Optional[int]
) -> None:
    """
    复制结果缺少文件 ID 时从 pickcode 恢复，无法确认身份时不写入索引或 STRM
    """
    helper, namespace, expected = _transfer_environment(tmp_path)
    file = SimpleNamespace(storage=storage, path="/Movies/Example/movie.mkv", name="movie.mkv", pickcode="12345678901234567", fileid=fileid)
    file.model_copy = lambda update: SimpleNamespace(**(vars(file) | update))
    transfer = SimpleNamespace(target_item=file, target_diritem=SimpleNamespace(path="/Movies/Example"), transfer_type="copy")
    transfer.model_copy = lambda update: SimpleNamespace(**(vars(transfer) | update))
    client = SimpleNamespace(to_id=MagicMock(return_value=resolved_id))
    helper.do_generate(client, {"transferinfo": transfer, "meta": None, "mediainfo": None}, "video", None)
    assert transfer.target_item is file
    assert transfer.target_item.fileid == fileid
    if not fileid and not resolved_id:
        assert not (tmp_path / "Example/movie.strm").exists()
        namespace["FileDbHelper"].return_value.upsert_batch.assert_not_called()
        return
    assert (tmp_path / "Example/movie.strm").read_text("utf8") == expected
    indexed = namespace["FileDbHelper"].return_value.process_fileitem.call_args.kwargs["fileitem"]
    assert indexed.fileid == (fileid or "456")
    assert client.to_id.call_count == (0 if fileid else 1)


@pytest.mark.parametrize("payload_type", ["model", "dict"])
def test_transfer_with_real_host_models_and_pickcode(tmp_path: Path, payload_type: str) -> None:
    """
    使用真实宿主模型、内置 pickcode 转换及实际索引转换方法验证复制结果
    """
    host = os.environ.get("MOVIEPILOT_SOURCE")
    if not host:
        pytest.skip("MOVIEPILOT_SOURCE required for actual transfer models")
    nodes = []
    for relative, names in [("app/schemas/file.py", {"FileURI", "FileItem"}),
                            ("app/schemas/transfer.py", {"TransferInfo"})]:
        tree = ast.parse((Path(host) / relative).read_text("utf8"))
        nodes.extend(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names)
    models = dict(BaseModel=BaseModel, Field=Field, Optional=Optional, Path=Path)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "host-transfer-models", "exec"), models)
    file_model, transfer_model = models["FileItem"], models["TransferInfo"]
    file_model.model_rebuild(_types_namespace=models)
    transfer_model.model_rebuild(_types_namespace=models)
    codec = {}
    with ZipFile(next((PLUGIN / "wheels").glob("p115pickcode-*.whl"))) as wheel:
        exec(compile(wheel.read("p115pickcode/__init__.py"), "bundled-pickcode", "exec"), codec)
    file_id = 1234567890123456789
    pickcode = codec["id_to_pickcode"](file_id)
    assert len(pickcode) == 17
    target = file_model(storage="u115", type="file", path="/Movies/Example/movie.mkv",
                        name="movie.mkv", pickcode=pickcode, modify_time=123, parent_fileid="2")
    transfer = transfer_model(target_item=target, target_diritem=file_model(path="/Movies/Example"),
                              transfer_type="copy")
    payload = transfer if payload_type == "model" else transfer.model_dump()
    original = transfer.model_dump()
    helper, namespace, expected = _transfer_environment(tmp_path)
    namespace["TransferInfo"] = transfer_model
    tree = ast.parse((PLUGIN / "db_manager/file_oper.py").read_text("utf8"))
    convert = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "process_fileitem")
    convert.decorator_list = []
    conversions = dict(Optional=Optional, FileItem=file_model, Path=Path)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), convert], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "file-index-conversion", "exec"), conversions)
    database = namespace["FileDbHelper"].return_value
    database.process_fileitem.side_effect = conversions["process_fileitem"]
    helper.do_generate(SimpleNamespace(to_id=codec["to_id"]), {"transferinfo": payload}, "video", None)
    assert (tmp_path / "Example/movie.strm").read_text("utf8") == expected
    batch = database.upsert_batch.call_args.args[0]
    assert batch[0]["data"]["id"] == file_id
    assert batch[0]["data"]["parent_id"] == 2
    assert batch[0]["data"]["pickcode"] == pickcode
    assert transfer.model_dump() == original
    if payload_type == "dict":
        assert payload == original
