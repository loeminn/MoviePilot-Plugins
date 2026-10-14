"""隔离宿主与网络边界，验证上游业务修复在本地实现中的行为"""

import __future__
import ast
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from hashlib import sha256
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Optional, Set
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest


PLUGIN = Path(__file__).resolve().parents[2] / "plugins.v3/p115strmhelper"


def _load(
    relative: str, class_name: Optional[str] = None, methods: Optional[Set[str]] = None, **namespace: Any
) -> Any:
    tree = ast.parse((PLUGIN / relative).read_text("utf8"))
    if class_name:
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
        cls.decorator_list = []
        cls.bases = []
        cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in methods]
        nodes = [cls]
    else:
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = dict(logger=MagicMock(), **namespace)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(PLUGIN / relative), "exec",
                 flags=__future__.annotations.compiler_flag), namespace)
    return namespace[class_name] if class_name else namespace


@pytest.mark.parametrize("parent_source,parent_id,parent_type,expected", [
    ("tmdb", "12", "movie", "parent"),
    ("tmdb", "13", "movie", "file"),
    ("douban", "12", "movie", "file"),
    ("tmdb", "12", "tv", "file"),
    (None, None, "movie", "file"),
])
def test_scrape_does_not_match_missing_imdb_ids(
    tmp_path: Path, parent_source: Optional[str], parent_id: Optional[str], parent_type: str, expected: str
) -> None:
    """
    IMDb 编号均为空时，只有来源、原生编号和媒体类型一致才刮削父目录
    """
    media_type = Enum("MediaType", {"MOVIE": "movie", "TV": "tv"})
    video = tmp_path / "movie.mkv"
    video.touch()
    media = SimpleNamespace(media_source="tmdb", media_id="12", type=media_type.MOVIE, imdb_id=None)
    parent = SimpleNamespace(media_source=parent_source, media_id=parent_id,
                             type=media_type(parent_type), imdb_id=None)
    chain = MagicMock()
    chain.recognize_by_meta.side_effect = [media, parent]
    events = MagicMock()
    namespace = _load("core/scrape.py", Path=Path, MediaType=media_type, MediaChain=lambda: chain,
                      MetaInfoPath=lambda path: path, eventmanager=events,
                      resolve_media_identity=lambda item: (item.media_source, item.media_id),
                      EventType=SimpleNamespace(MetadataScrape="scrape"), FileItem=SimpleNamespace)
    namespace["media_scrape_metadata"](video)
    item = events.send_event.call_args.args[1]["fileitem"]
    assert Path(item.path) == (tmp_path if expected == "parent" else video)


@pytest.mark.parametrize("raw_id,expected", [("0", False), (" ", False), (None, False), (" 12 ", True)])
def test_scrape_uses_host_identity_normalization(raw_id: Optional[str], expected: bool) -> None:
    """
    宿主判为无效的身份不能参与匹配，别名规范化后的身份可以匹配
    """
    host = os.environ.get("MOVIEPILOT_SOURCE")
    if not host:
        pytest.skip("MOVIEPILOT_SOURCE required for actual identity normalization")
    types = ast.parse((Path(host) / "app/schemas/types.py").read_text("utf8"))
    nodes = [node for node in types.body if isinstance(node, ast.ClassDef) and node.name in {"MediaType", "MediaSource"}]
    media = ast.parse((Path(host) / "app/schemas/media.py").read_text("utf8"))
    nodes.extend(node for node in media.body if
                 (isinstance(node, ast.FunctionDef) and node.name in {"normalize_media_source", "resolve_media_identity"})
                 or (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "MEDIA_SOURCE_ALIASES" for target in node.targets)))
    host_namespace = {"Enum": Enum}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "host-media-identity", "exec",
                 flags=__future__.annotations.compiler_flag), host_namespace)
    media_type = host_namespace["MediaType"]
    resolver = host_namespace["resolve_media_identity"]
    namespace = _load("core/scrape.py", MediaType=media_type, resolve_media_identity=resolver)
    left = SimpleNamespace(media_source="TMDB", media_id=raw_id, type=media_type.MOVIE)
    right = SimpleNamespace(media_source="themoviedb", media_id=raw_id, type=media_type.MOVIE)
    assert namespace["_same_media_identity"](left, right) is expected


@pytest.mark.parametrize("tmdb_id", [None, "", 0, "0", -1, "-1", "abc", "²", "①"])
def test_sync_delete_rejects_missing_identity(tmdb_id: Any) -> None:
    """
    缺少有效身份时不执行任何历史查询
    """
    cls = _load("helper/mediasyncdel/__init__.py", "MediaSyncDelHelper", {"__get_transfer_his"})
    helper = cls()
    helper.transferhis = MagicMock()
    assert helper._MediaSyncDelHelper__get_transfer_his("Movie", "Example", "/a", tmdb_id, None, None) == ("", [])
    assert not helper.transferhis.mock_calls


@pytest.mark.parametrize("kind", ["transfer", "strm"])
def test_share_queue_handles_enqueue_during_idle_exit(kind: str) -> None:
    """
    工作线程读到空队列后到退出前入队的任务仍会被消费
    """
    if kind == "transfer":
        cls = _load("helper/share/__init__.py", "ShareTransferHelper",
                    {"__init__", "add_share", "_ensure_add_share_worker_running", "_process_add_share_queue"},
                    Queue=Queue, Lock=Lock, Thread=Thread, Empty=Empty, sleep=lambda _: None)
        helper = cls(None, None)
        queue_attr, worker_attr = "_add_share_queue", "_add_share_worker_thread"
        enqueue = lambda: helper.add_share("share", "channel", "user")
        consume = helper._process_add_share_queue
        handled = MagicMock()
        helper._ShareTransferHelper__add_share = handled
    else:
        cls = _load("helper/strm/share/create.py", "ShareInteractiveGenStrmQueue",
                    {"__init__", "enqueue", "_ensure_worker_running", "_process_queue"},
                    Queue=Queue, Lock=Lock, Thread=Thread, Empty=Empty, sleep=lambda _: None)
        helper = cls()
        queue_attr, worker_attr = "_task_queue", "_worker_thread"
        enqueue = lambda: helper.enqueue("share", "channel", "user")
        consume = helper._process_queue
        handled = MagicMock()
        helper._run_job = handled

    class RacingQueue(Queue):
        """
        模拟阻塞读取超时后生产者立即提交新任务
        """

        def get(self, block: bool = True, timeout: Optional[float] = None) -> Any:
            """
            首次读取交错入队，后续读取立即返回结果
            """
            if not getattr(self, "raced", False):
                self.raced = True
                enqueue()
                raise Empty
            return super().get(block=False)

    queue = RacingQueue()
    setattr(helper, queue_attr, queue)
    setattr(helper, worker_attr, SimpleNamespace(is_alive=lambda: True))
    consume()
    handled.assert_called_once()
    assert queue.unfinished_tasks == 0
    assert getattr(helper, worker_attr) is None


@pytest.mark.parametrize("path", ["invalid", "/local#/cloud"])
def test_full_sync_joins_workers_after_failure(path: str) -> None:
    """
    配置错误或网盘查询失败后写入及结果线程全部结束
    """
    threads = []

    def _start_thread(*args: Any, **kwargs: Any) -> Thread:
        thread = Thread(*args, **kwargs)
        threads.append(thread)
        return thread

    cls = _load("helper/strm/full/__init__.py", "FullSyncStrmHelper",
                {"generate_strm_files", "__io_writer_worker"},
                configer=SimpleNamespace(full_sync_process_rust=False, full_sync_process_num=1),
                Processor=None, Thread=_start_thread, ThreadPoolExecutor=ThreadPoolExecutor,
                Empty=Empty, CBase64=SimpleNamespace(encode=lambda value: value),
                get_pid_by_path=MagicMock(side_effect=RuntimeError("network unavailable")),
                sentry_manager=MagicMock())
    helper = cls()
    helper.write_queue, helper.result_queue = Queue(), Queue()
    helper.remove_unless_strm = True
    helper.client = None
    scanner = MagicMock()
    helper._FullSyncStrmHelper__remove_unless_strm_local = lambda _: scanner
    try:
        if path == "invalid":
            with pytest.raises(IndexError):
                helper.generate_strm_files(path)
        else:
            assert helper.generate_strm_files(path) is False
            scanner.join.assert_called_once()
        assert threads and all(not thread.is_alive() for thread in threads)
    finally:
        for _ in range(8):
            helper.write_queue.put(None)
        for thread in threads:
            thread.join(timeout=1)


def test_increment_sync_waits_for_local_scan_on_cloud_failure() -> None:
    """
    云端扫描异常时等待本地扫描结束后才退出
    """
    cls = _load("helper/strm/increment.py", "IncrementSyncStrmHelper", {"generate_strm_files"},
                configer=SimpleNamespace(increment_sync_second_level_dir_scan=False),
                deque=deque, perf_counter=perf_counter, sentry_manager=MagicMock(),
                ItertreeInternalError=type("ItertreeInternalError", (Exception,), {}))
    helper = cls()
    scanner = MagicMock()
    helper._IncrementSyncStrmHelper__generate_local_tree = lambda **_: scanner
    helper._IncrementSyncStrmHelper__generate_pan_tree = MagicMock(side_effect=RuntimeError("network"))
    helper.generate_strm_files("/local#/cloud")
    scanner.join.assert_called_once()


@pytest.mark.parametrize("status", [None, 200, 500])
def test_emby_probe_handles_timeout_and_http_errors(status: Optional[int]) -> None:
    """
    慢速媒体探测采用独立超时并正确报告无响应及 HTTP 错误
    """
    response = None if status is None else MagicMock(status_code=status)
    if response is not None:
        response.__enter__.return_value = response
    request = MagicMock()
    request.return_value.post_res.return_value = response
    cls = _load("helper/mediaserver/emby.py", "EmbyOperate", {"trigger_mediainfo_refresh"}, RequestUtils=request)
    helper = cls()
    helper.func_name = "test"
    helper.get_emby_info = lambda _: ("http://emby/", "user", "key")
    assert helper.trigger_mediainfo_refresh("emby", "1") is (status == 200)
    request.assert_called_once_with(timeout=120)


@pytest.mark.parametrize("retry", [False, True])
def test_open_existing_folder_response_survives_retry(retry: bool) -> None:
    """
    已存在目录业务码交给建目录调用方处理，重试不丢失允许的业务码
    """
    cls = _load("core/u115_open.py", "U115OpenHelper", {"_request_api", "create_folder"},
                Path=Path, randint=lambda *_: 0, sleep=lambda _: None,
                RequestError=httpx.RequestError, HTTPStatusError=httpx.HTTPStatusError)
    helper = cls()
    helper.base_url = "https://example.invalid"
    helper._check_session = lambda: None
    payload = {"code": 20004, "state": False, "message": "directory exists"}
    response = httpx.Response(200, json=payload, request=httpx.Request("POST", helper.base_url))
    responses = [response]
    if retry:
        responses.insert(0, httpx.Response(503, request=httpx.Request("POST", helper.base_url)))
    helper.session = MagicMock()
    helper.session.request.side_effect = responses
    target = SimpleNamespace(fileid="2")
    helper.get_item = MagicMock(return_value=target)
    assert helper.create_folder(SimpleNamespace(path="/root", fileid="1"), "existing") is target
    helper.get_item.assert_called_once_with(Path("/root/existing"))
    for call in helper.session.request.call_args_list:
        assert "accepted_codes" not in call.kwargs


@pytest.mark.parametrize("status", [429, 503])
def test_open_request_stops_after_retry_budget(status: int) -> None:
    """
    持续限流或服务错误在重试额度耗尽后返回，不再发起请求或等待
    """
    sleep = MagicMock()
    cls = _load("core/u115_open.py", "U115OpenHelper", {"_request_api"},
                sleep=sleep, RequestError=httpx.RequestError, HTTPStatusError=httpx.HTTPStatusError)
    helper = cls()
    helper.base_url = "https://example.invalid"
    helper._check_session = lambda: None
    response = httpx.Response(status, request=httpx.Request("POST", helper.base_url))
    helper.session = MagicMock()
    helper.session.request.side_effect = [response] * 3
    assert helper._request_api("POST", "/test", retry_limit=2) is None
    assert helper.session.request.call_count == 3
    assert sleep.call_count == 2


@pytest.mark.parametrize("payload", [{"code": 1}, {"code": 1, "message": None}])
def test_open_error_without_message_returns_none(payload: dict) -> None:
    """
    不包含有效消息的业务错误正常返回失败
    """
    cls = _load("core/u115_open.py", "U115OpenHelper", {"_request_api"},
                RequestError=httpx.RequestError, HTTPStatusError=httpx.HTTPStatusError)
    helper = cls()
    helper.base_url = "https://example.invalid"
    helper._check_session = lambda: None
    helper.session = MagicMock()
    helper.session.request.return_value = httpx.Response(
        200, json=payload, request=httpx.Request("POST", helper.base_url)
    )
    assert helper._request_api("POST", "/test") is None
    helper.session.request.assert_called_once()


@pytest.mark.parametrize("first_status", [429, 503, 200])
@pytest.mark.parametrize("quiet", [True, False])
def test_open_retry_preserves_error_logging_preference(first_status: int, quiet: bool) -> None:
    """
    各类重试均保留业务错误日志开关，内部控制参数不传给 HTTP 客户端
    """
    cls = _load("core/u115_open.py", "U115OpenHelper", {"_request_api"},
                sleep=lambda _: None, RequestError=httpx.RequestError, HTTPStatusError=httpx.HTTPStatusError)
    helper = cls()
    helper.base_url = "https://example.invalid"
    helper.retry_delay = 1
    helper._check_session = lambda: None
    request = httpx.Request("POST", helper.base_url)
    helper.session = MagicMock()
    helper.session.request.side_effect = [
        httpx.Response(first_status, json={"code": 1, "message": "已达到当前访问上限"}, request=request),
        httpx.Response(200, json={"code": 2, "message": "missing"}, request=request),
    ]
    logger = helper._request_api.__globals__["logger"]
    assert helper._request_api("POST", "/test", no_error_log=quiet) is None
    assert logger.warn.call_count == (0 if quiet else 1 + (first_status == 200))
    assert helper.session.request.call_count == 2
    for call in helper.session.request.call_args_list:
        assert "no_error_log" not in call.kwargs
        assert "retry_limit" not in call.kwargs


def test_redis_directory_tree_uses_full_path(tmp_path: Path) -> None:
    """
    相同文件名位于不同任务目录时不会共用 Redis 键
    """
    redis_helper = MagicMock()
    storage = _load("utils/tree.py", "RedisStorage", {"__init__"},
                    RedisHelper=lambda: redis_helper, sha256=sha256, __package__="plugin.utils")
    tree = _load("utils/tree.py", "DirectoryTree", {"__init__"},
                 settings=SimpleNamespace(CACHE_BACKEND_TYPE="redis"), RedisStorage=storage)
    left = tree(tmp_path / "one/tree.txt")
    right = tree(tmp_path / "two/tree.txt")
    repeated = tree(tmp_path / "one/tree.txt")
    assert left._storage._set_key != right._storage._set_key
    assert left._storage._list_key != right._storage._list_key
    assert left._storage._set_key == repeated._storage._set_key


def test_missing_share_preserves_native_identity() -> None:
    """
    非旧版四种来源的编号也保留在失效分享记录中
    """
    sources = Enum("MediaSource", {"TMDB": "themoviedb", "TVDB": "tvdb", "IMDb": "imdb", "Douban": "douban"}, type=str)
    cls = _load("helper/strm/share/cleaner.py", "ShareStrmMissingMediaStore", {"row_from_transfer_history"},
                uuid4=uuid4, time_unix=lambda: 123, MediaSource=sources)
    row = cls.row_from_transfer_history(SimpleNamespace(media_source="bangumi", media_id="12"), "/a.strm", "s", "c")
    assert (row["media_source"], row["media_id"]) == ("bangumi", "12")
    assert all(row[key] is None for key in ("tmdbid", "tvdbid", "imdbid", "doubanid"))


@pytest.mark.parametrize("result", ["error", "present", "absent"])
def test_backup_slot_is_only_released_after_confirmed_removal(result: str) -> None:
    """
    调度查询失败或任务仍存在时不释放备份占位
    """
    scheduler = MagicMock(return_value=[SimpleNamespace(id="job")] if result == "present" else [])
    if result == "error":
        scheduler.side_effect = RuntimeError("scheduler unavailable")
    cls = _load("service/backup/__init__.py", "BackupService", {"_watch_orphaned_reserved_slot"},
                sleep=lambda _: None, list_scheduler_jobs=scheduler,
                Thread=lambda target, **_: SimpleNamespace(start=target))
    helper = cls()
    helper._backup_task_lock = Lock()
    helper._backup_running_tasks = {"backup"}
    helper._reserved_task_started = set()
    helper._release_backup_task = MagicMock()
    helper._watch_orphaned_reserved_slot("backup", "job", grace_sec=0)
    assert helper._release_backup_task.call_count == (1 if result == "absent" else 0)
