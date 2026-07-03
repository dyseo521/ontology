"""HTTP 유틸 — 재시도 + 소스별 User-Agent 규약.

- SEC EDGAR: 연락처 포함 UA 필수 (차단 방지)
- Yahoo RSS / Naver: 브라우저 UA 필요
"""
from __future__ import annotations

import time

import requests

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SEC_UA = "ontoquant-research/0.1 (contact: claude.code.dyseo@gmail.com)"

_session = requests.Session()


def get(url: str, params: dict | None = None, headers: dict | None = None,
        timeout: int = 30, retries: int = 3, backoff: float = 2.0) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = _session.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001 — 재시도 대상
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"GET {url} 실패 ({retries}회): {last_exc}")
