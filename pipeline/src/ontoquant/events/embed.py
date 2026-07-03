"""임베딩 인덱스 — intfloat/multilingual-e5-small (한/영 통합, CPU 추론).

인덱스: data/embeddings/index.npz {ids: str[N], vectors: float32[N,384] (정규화됨)}
sentence-transformers 미설치 환경에서는 조용히 비활성화 (분류는 규칙만으로 동작).
"""
from __future__ import annotations

import numpy as np

from ontoquant import config

MODEL_NAME = "intfloat/multilingual-e5-small"
INDEX_PATH = config.EMBEDDINGS_DIR / "index.npz"

_model = None


def available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def encode(texts: list[str], prefix: str = "passage: ") -> np.ndarray:
    model = _get_model()
    vecs = model.encode([prefix + t for t in texts], normalize_embeddings=True,
                        show_progress_bar=False, batch_size=32)
    return np.asarray(vecs, dtype=np.float32)


class EmbeddingIndex:
    def __init__(self):
        if INDEX_PATH.exists():
            data = np.load(INDEX_PATH, allow_pickle=False)
            self.ids: list[str] = [str(x) for x in data["ids"]]
            self.vectors: np.ndarray = data["vectors"]
        else:
            self.ids, self.vectors = [], np.zeros((0, 384), dtype=np.float32)
        self._id_set = set(self.ids)

    def has(self, eid: str) -> bool:
        return eid in self._id_set

    def add(self, ids: list[str], vectors: np.ndarray) -> None:
        fresh = [(i, v) for i, v in zip(ids, vectors) if i not in self._id_set]
        if not fresh:
            return
        self.ids.extend(i for i, _ in fresh)
        self._id_set.update(i for i, _ in fresh)
        self.vectors = np.vstack([self.vectors, np.stack([v for _, v in fresh])])

    def save(self) -> None:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(INDEX_PATH, ids=np.array(self.ids), vectors=self.vectors)

    def vector_of(self, eid: str) -> np.ndarray | None:
        try:
            return self.vectors[self.ids.index(eid)]
        except ValueError:
            return None

    def search(self, query_vec: np.ndarray, top_k: int = 10,
               exclude: set[str] | None = None) -> list[tuple[str, float]]:
        if len(self.ids) == 0:
            return []
        sims = self.vectors @ query_vec
        order = np.argsort(-sims)
        out = []
        for idx in order:
            eid = self.ids[idx]
            if exclude and eid in exclude:
                continue
            out.append((eid, float(sims[idx])))
            if len(out) >= top_k:
                break
        return out

    def search_text(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        vec = encode([query], prefix="query: ")[0]
        return self.search(vec, top_k)
