"""감사 로그 — 모든 액션 제출의 append-only 기록 (decision lineage의 원천)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ontoquant import config


def _log_path(overlay_dir: Path | None = None) -> Path:
    if overlay_dir:
        return overlay_dir / "action_log.jsonl"
    return config.WRITEBACK_DIR / "action_log.jsonl"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_action(
    action_type: str,
    parameters: dict,
    actor: str,
    status: str,
    criteria_results: list[dict] | None = None,
    objects_changed: list[dict] | None = None,
    detail: str | None = None,
    overlay_dir: Path | None = None,
) -> dict:
    entry = {
        "actionLogId": new_id("act"),
        "actionType": action_type,
        "parameters": parameters,
        "actor": actor,
        "submittedAt": now_iso(),
        "status": status,  # SUBMITTED | REJECTED_CRITERIA | FAILED
        "criteriaResults": criteria_results or [],
        "objectsChanged": objects_changed or [],
    }
    if detail:
        entry["detail"] = detail
    path = _log_path(overlay_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_log(limit: int | None = None) -> list[dict]:
    path = _log_path()
    if not path.exists():
        return []
    entries = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    entries.reverse()
    return entries[:limit] if limit else entries
