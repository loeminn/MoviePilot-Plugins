from asyncio import get_running_loop, run
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List
from app.db.oper.transferhistory import TransferHistoryOper

from app.sdk.utilities import cut as jieba_cut


class TransferHBOper:
    """
    历史记录数据库操作扩展
    """

    def get_transfer_his_by_path_title(self, path: str) -> List[Any]:
        """
        通过路径查询转移记录
        所有匹配项

        :param path (str): 查询路径

        :return List: 数据列表
        """
        words = [word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                 for word in jieba_cut(path, HMM=False)]
        if not words:
            return []
        pattern = "%" + "%".join(words) + "%"

        async def query() -> List[Any]:
            return await TransferHistoryOper().async_list_by_title(
                title=pattern, page=1, count=-1, wildcard=True
            )

        try:
            get_running_loop()
        except RuntimeError:
            return run(query())
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: run(query())).result()
