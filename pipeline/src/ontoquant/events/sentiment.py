"""뉴스 감성 — 한국어: KR-FinBERT-SC (금융 특화), 영어: e5 센트로이드 근사.

점수 규약: -1(부정) ~ +1(긍정). label ∈ {POSITIVE, NEGATIVE, NEUTRAL}.
모델 미설치/로드 실패 시 조용히 비활성화 (감성은 보조 신호).
HF 토큰(huggingface.txt)은 다운로드 안정화용 — 공개 모델이라 없어도 동작.
"""
from __future__ import annotations

import os
import re

from ontoquant import config

KR_MODEL = "snunlp/KR-FinBert-SC"
_pipeline = None
_available: bool | None = None

EN_POS = "shares surge record profit beat expectations upgrade growth strong demand"
EN_NEG = "shares plunge loss lawsuit downgrade miss weak decline recall investigation"


def _load_hf_token() -> None:
    path = config.ROOT / "huggingface.txt"
    if path.exists() and not os.environ.get("HF_TOKEN"):
        m = re.search(r'["\'](hf_[A-Za-z0-9]+)["\']', path.read_text())
        if m:
            os.environ["HF_TOKEN"] = m.group(1)


def available() -> bool:
    global _available
    if _available is None:
        try:
            import transformers  # noqa: F401
            _available = True
        except ImportError:
            _available = False
    return _available


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        _load_hf_token()
        from transformers import pipeline
        _pipeline = pipeline("text-classification", model=KR_MODEL, top_k=None,
                             truncation=True, max_length=256)
    return _pipeline


def _is_korean(text: str) -> bool:
    hangul = len(re.findall(r"[가-힣]", text))
    return hangul >= max(3, len(text) * 0.1)


def analyze_korean(texts: list[str]) -> list[tuple[float, str]]:
    """KR-FinBERT-SC: 클래스 확률로 부호 있는 점수 산출."""
    pipe = _get_pipeline()
    out = []
    for scores in pipe(texts, batch_size=16):
        by_label = {s["label"].lower(): s["score"] for s in scores}
        score = by_label.get("positive", 0.0) - by_label.get("negative", 0.0)
        label = ("POSITIVE" if score > 0.25 else "NEGATIVE" if score < -0.25 else "NEUTRAL")
        out.append((round(score, 3), label))
    return out


def analyze_english(texts: list[str]) -> list[tuple[float, str]]:
    """e5 센트로이드 근사 (긍정/부정 방향 벡터 대비 코사인 차)."""
    from ontoquant.events import embed as emb
    if not emb.available():
        return [(0.0, "NEUTRAL")] * len(texts)
    import numpy as np
    pos, neg = emb.encode([EN_POS, EN_NEG])
    vecs = emb.encode(texts)
    out = []
    for v in vecs:
        raw = float(v @ pos - v @ neg)
        score = round(float(np.clip(raw * 8, -1, 1)), 3)  # e5 코사인 차는 스케일이 작다
        label = ("POSITIVE" if score > 0.3 else "NEGATIVE" if score < -0.3 else "NEUTRAL")
        out.append((score, label))
    return out


def analyze(texts: list[str]) -> list[tuple[float, str]]:
    """언어 자동 분기. 실패 시 NEUTRAL."""
    results: list[tuple[float, str] | None] = [None] * len(texts)
    kr_idx = [i for i, t in enumerate(texts) if _is_korean(t)]
    en_idx = [i for i in range(len(texts)) if i not in set(kr_idx)]
    if kr_idx and available():
        try:
            for i, r in zip(kr_idx, analyze_korean([texts[i] for i in kr_idx])):
                results[i] = r
        except Exception:  # noqa: BLE001 — 모델 실패는 보조 신호 포기
            pass
    if en_idx:
        try:
            for i, r in zip(en_idx, analyze_english([texts[i] for i in en_idx])):
                results[i] = r
        except Exception:  # noqa: BLE001
            pass
    return [r if r is not None else (0.0, "NEUTRAL") for r in results]
