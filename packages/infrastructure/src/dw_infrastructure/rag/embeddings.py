"""嵌入器 —— Phase 4。

嵌入器职责单一：`embed(texts) -> list[list[float]]`，维度由 `dim` 暴露。
`FakeEmbedder` 用稳定哈希把「token → 向量桶」做 L2 归一化，保证：
* 同输入同向量（确定性，CI 可复现）；
* 共享 token 越多方向越接近（相似度有区分度，测试可断言 top-k）。
真实语义嵌入由 `OpenAIEmbedder` 提供，仅在 `Settings.rag_embedder_kind="openai"` 时启用。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from dw_infrastructure.config import Settings

# token：CJK 单字 或 连续的 ASCII 字母/数字串
_TOKEN_PATTERN = re.compile(r"[一-鿿]|[A-Za-z0-9]+")

DEFAULT_EMBEDDING_DIM = 256


@runtime_checkable
class Embedder(Protocol):
    """嵌入器协议：把文本变成定长向量。"""

    dim: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """确定性伪嵌入器：零外部依赖，仅用于测试 / 本地演示。"""

    def __init__(self, dim: int = DEFAULT_EMBEDDING_DIM) -> None:
        if dim <= 0:
            raise ValueError("嵌入维度必须为正")
        self.dim = dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _TOKEN_PATTERN.findall(text.lower()):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            # 用第二段字节决定符号，让不同 token 在同一桶里能相互抵消，
            # 从而「共享 token 越多，余弦越接近」。
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


class OpenAIEmbedder:
    """真实嵌入器接缝（OpenAI 兼容）：仅在显式配置时启用，非测试默认。

    注意：OpenAI 文本嵌入（如 text-embedding-3-small）固定 1536 维，启用时须将
    `Settings.rag_embedding_dim` 一并调整为对应维度并重新生成迁移（列维度与模型一致）。
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
        dim: int = 1536,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAIEmbedder 需要 api_key")
        # 懒导入：避免未安装 openai 时影响测试环境
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self.dim = dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self._model, input=list(texts))
        return [item.embedding for item in response.data]


def build_embedder(settings: Settings) -> Embedder:
    """按配置选择嵌入器。默认 fake（确定性、零依赖）。"""
    if settings.rag_embedder_kind == "openai":
        return OpenAIEmbedder(
            api_key=settings.rag_openai_api_key or "",
            model=settings.rag_openai_embed_model,
            base_url=settings.rag_openai_base_url,
            dim=settings.rag_embedding_dim,
        )
    return FakeEmbedder(dim=settings.rag_embedding_dim)
