import math
from collections import Counter
import numpy as np

class BM25Index:
    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.corpus = []       # 文档列表
        self.doc_len = []
        self.avgdl = 0.0
        self.idf = {}
        self.doc_freqs = []
        self.N = 0

    def build(self, documents: list):
        self.corpus = documents
        self.N = len(documents)
        self.doc_len = [len(doc.split()) for doc in documents]
        self.avgdl = sum(self.doc_len) / self.N if self.N > 0 else 0
        # 计算文档频率
        df = Counter()
        for doc in documents:
            words = set(doc.split())
            for w in words:
                df[w] += 1
        # 计算IDF
        self.idf = {w: math.log((self.N - freq + 0.5) / (freq + 0.5) + 1) for w, freq in df.items()}
        # 计算每个文档的词频
        self.doc_freqs = [Counter(doc.split()) for doc in documents]

    def search(self, query: str, top_k=30):
        query_words = query.split()
        scores = np.zeros(self.N)
        for i in range(self.N):
            f = self.doc_freqs[i]
            dl = self.doc_len[i]
            for w in query_words:
                if w in self.idf:
                    tf = f[w]
                    score = self.idf[w] * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
                    scores[i] += score
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(idx, scores[idx]) for idx in top_indices]