from typing import List

from sqlalchemy import or_, select
from app.db.oper.transferhistory import TransferHistoryOper
from app.db.models.transferhistory import TransferHistory

from app.sdk.utilities import cut as jieba_cut


class TransferHBOper(TransferHistoryOper):
    """
    历史记录数据库操作扩展
    """

    def get_transfer_his_by_path_title(self, path: str) -> List[TransferHistory]:
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
        statement = select(TransferHistory).where(or_(
            TransferHistory.title.like(pattern, escape="\\"),
            TransferHistory.src.like(pattern, escape="\\"),
            TransferHistory.dest.like(pattern, escape="\\"),
        )).order_by(TransferHistory.date.desc())
        return self._execute_sync_query(
            lambda session: list(session.execute(statement).scalars().all())
        )
