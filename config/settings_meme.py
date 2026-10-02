"""表情包语义检索配置"""
from __future__ import annotations

from config._base import BaseSettings, Field, SettingsConfigDict


class MemeSearchSettings(BaseSettings):
    """表情包语义检索配置。

    控制运行时 [MEME:自然语言描述] 标签的语义检索行为。
    索引文件位于 data/memes/_index/，由 scripts/meme/ 下脚本离线生成。
    """

    enabled: bool = Field(
        default=True,
        description="是否启用语义检索（关闭时 [MEME:非分类名] 直接 fallback 到 random）",
    )
    top_k: int = Field(
        default=5,
        description="检索返回前 K 个候选，从中带权随机选一张",
        ge=1,
        le=20,
    )
    min_similarity: float = Field(
        default=0.25,
        description="最低余弦相似度阈值，低于此值不作为候选",
        ge=0.0,
        le=1.0,
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_MEME_SEARCH_",
        extra="allow",
    )
