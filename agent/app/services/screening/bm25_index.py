"""BM25 稀疏检索（rank_bm25 内存版，中文按字符二元分词兜底）。"""
from __future__ import annotations

import re
from typing import List, Tuple

from rank_bm25 import BM25Plus

_TOKEN_RE = re.compile(r"[A-Za-z0-9_+#./-]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> List[str]:
    """英文按词、中文按字切分（轻量、零依赖）。"""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


class BM25Index:
    """内存 BM25 索引。corpus 直接使用候选人简历文本，索引槽位即候选人下标。

    采用 BM25Plus：小语料（如单岗位候选人池）下 Okapi 的 idf 会退化为 0，
    BM25Plus 的 idf 恒正，保证稀疏召回可用。
    """

    def __init__(self, corpus: List[str]) -> None:
        self.corpus = corpus
        tokenized = [tokenize(doc) for doc in corpus]
        self._bm25 = BM25Plus(tokenized) if any(tokenized) else None

    def search(self, query: str, top_k: int = 30) -> List[Tuple[int, float]]:
        """返回 [(corpus_index, score)]，按分数降序。"""
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [(i, float(scores[i])) for i in order[:top_k] if scores[i] > 0]
