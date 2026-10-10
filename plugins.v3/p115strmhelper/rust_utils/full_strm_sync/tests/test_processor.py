"""
验证安装后的全量同步扩展的 Python 接口及批次分类行为
"""

import json
from typing import Any, Dict

import pytest

from full_strm_sync import PackedResult, Processor


@pytest.fixture
def config() -> Dict[str, Any]:
    """
    创建包含媒体、字幕及过滤条件的处理配置
    """

    return {
        "pan_transfer_enabled": False,
        "pan_transfer_paths": [],
        "auto_download_mediainfo": True,
        "rmt_mediaext_set": [".mkv", ".mp4"],
        "download_mediaext_set": [".srt"],
        "strm_generate_blacklist": ["trailer"],
        "mediainfo_download_whitelist": [],
        "mediainfo_download_blacklist": [],
        "full_sync_min_file_size": 100,
        "pan_media_dir": "/media/",
    }


def _file(name: str, **overrides: Any) -> Dict[str, Any]:
    return {
        "name": name,
        "path": f"/media/{name}",
        "is_dir": False,
        "size": 200,
        "pickcode": "12345678901234567",
        "sha1": "a" * 40,
        **overrides,
    }


def test_batch_exposes_typed_results(config: Dict[str, Any]) -> None:
    """
    验证媒体与字幕分流、过滤条件及失败结果可从 Python 读取
    """

    processor = Processor(json.dumps(config))
    result = processor.process_batch(json.dumps([
        _file("电影.mkv"),
        _file("电影.zh.srt"),
        _file("folder", is_dir=True),
        _file("TRAILER.mp4"),
        _file("small.mkv", size=1),
        _file("invalid.mkv", pickcode="bad"),
    ]))
    assert isinstance(result, PackedResult)
    assert len(result.strm_results) == 1
    media = result.strm_results[0]
    assert media.original_file_name == "电影.mkv"
    assert media.path_in_pan == "/media/电影.mkv"
    assert media.pickcode == "12345678901234567"
    assert len(result.download_results) == 1
    assert result.download_results[0].sha1 == "a" * 40
    assert {item.path_in_pan for item in result.skip_results} == {
        "/media/folder", "/media/TRAILER.mp4", "/media/small.mkv",
    }
    assert len(result.fail_results) == 1
    assert result.fail_results[0].path_in_pan == "/media/invalid.mkv"
    assert result.fail_results[0].reason
    with pytest.raises(AttributeError):
        media.pickcode = "changed"


def test_parallel_batch_retains_every_file(config: Dict[str, Any]) -> None:
    """
    验证并行聚合不丢失文件，且处理器可重复使用
    """

    processor = Processor(json.dumps(config))
    batch = [_file(f"episode-{index}.mkv") for index in range(100)]
    for _ in range(2):
        result = processor.process_batch(json.dumps(batch))
        assert {item.path_in_pan for item in result.strm_results} == {
            item["path"] for item in batch
        }
        assert len(result.strm_results) == 100
        assert not result.fail_results
    empty = processor.process_batch("[]")
    assert not any((empty.strm_results, empty.download_results, empty.skip_results, empty.fail_results))


@pytest.mark.parametrize("invalid", ["{", "[]", "{}"])
def test_invalid_config_raises_value_error(invalid: str) -> None:
    """
    验证配置解析错误转换为 Python 异常
    """

    with pytest.raises(ValueError):
        Processor(invalid)


def test_invalid_batch_raises_value_error(config: Dict[str, Any]) -> None:
    """
    验证批次解析错误不影响后续合法调用
    """

    processor = Processor(json.dumps(config))
    with pytest.raises(ValueError):
        processor.process_batch("{}")
    assert len(processor.process_batch(json.dumps([_file("valid.mkv")])).strm_results) == 1
