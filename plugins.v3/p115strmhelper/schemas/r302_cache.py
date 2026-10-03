from typing import List

from pydantic import BaseModel, Field


class DeleteR302CachePayload(BaseModel):
    """
    指定删除直链缓存的请求体
    """

    keys: List[str] = Field(..., min_length=1, max_length=100, description="要删除的完整缓存键")
