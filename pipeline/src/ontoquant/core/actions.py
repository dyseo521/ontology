"""ActionEngine — 액션 타입(파라미터·제출 기준·규칙·사이드 이펙트) 실행기.

제출 흐름:
  ① Parameters 해석 (기본값/필수/objectRef 바인딩)
  ② Submission Criteria 평가 — 하나라도 실패 시 거부 + failureMessage 목록 반환
  ③ Rules 순차 실행 — 모든 쓰기는 WriteBatch 에 스테이징, 전부 성공 시에만 커밋
  ④ Side Effects — 감사 로그(항상), 알림
모든 제출(성공/거부)은 action_log.jsonl 에 기록된다 (decision lineage).

표현식 평가: 스키마 YAML 은 레포 소유 코드와 동급의 신뢰 수준이므로
제한된 네임스페이스의 eval 을 사용한다 (외부 입력이 표현식이 되는 일은 없음).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Callable

from ontoquant.core import audit
from ontoquant.core.schema import ActionTypeDef
from ontoquant.core.store import LinkRecord, OntologyStore


class AttrView:
    """dict 를 표현식에서 obj.prop 로 읽게 하는 래퍼 (없는 키 → None)."""

    def __init__(self, data: dict | None):
        object.__setattr__(self, "_data", data or {})

    def __getattr__(self, name: str):
        val = self._data.get(name)
        return AttrView(val) if isinstance(val, dict) else val

    def __bool__(self) -> bool:
        return bool(self._data)

    def __eq__(self, other) -> bool:
        if other is None:
            return not self._data
        if isinstance(other, AttrView):
            return self._data == other._data
        return self._data == other

    def __ne__(self, other) -> bool:
        return not self.__eq__(other)

    def raw(self) -> dict:
        return self._data


class WriteBatch:
    """규칙 실행 결과를 스테이징했다가 전부 성공 시에만 커밋."""

    def __init__(self):
        self.objects: list[tuple[str, str, dict]] = []      # (layer, type, obj)
        self.links: list[tuple[str, LinkRecord]] = []       # (layer, rec)
        self.portfolio_doc: dict | None = None

    def upsert(self, layer: str, object_type: str, obj: dict) -> None:
        self.objects.append((layer, object_type, obj))

    def link(self, layer: str, rec: LinkRecord) -> None:
        self.links.append((layer, rec))

    def set_portfolio(self, doc: dict) -> None:
        self.portfolio_doc = doc

    def apply(self, store: OntologyStore, overlay: bool) -> list[dict]:
        changed = []
        for layer, otype, obj in self.objects:
            layer = "overlay" if overlay else layer
            store.append_object(layer, otype, obj)
            pk_field = store.schema.objectTypes[otype].primaryKey
            changed.append({"objectType": otype, "pk": obj.get(pk_field), "layer": layer})
        for layer, rec in self.links:
            store.append_link("overlay" if overlay else layer, rec)
            changed.append({"linkType": rec.linkType, "from": rec.fromPk, "to": rec.toPk})
        if self.portfolio_doc is not None:
            store.write_portfolio_doc(self.portfolio_doc, overlay=overlay)
            changed.append({"objectType": "Portfolio", "pk": "portfolio.json"})
        return changed


class CriteriaRejected(Exception):
    def __init__(self, failures: list[str]):
        super().__init__("; ".join(failures))
        self.failures = failures


# functionRule 레지스트리 — core/action_functions.py 가 채운다
FUNCTION_REGISTRY: dict[str, Callable[..., None]] = {}


def register_function(name: str):
    def deco(fn):
        FUNCTION_REGISTRY[name] = fn
        return fn
    return deco


class ActionEngine:
    def __init__(self, store: OntologyStore, actor: str = "user"):
        from ontoquant.core import action_functions  # noqa: F401 — FUNCTION_REGISTRY 등록
        self.store = store
        self.actor = actor
        self.overlay = store.overlay_dir is not None
        self._log_dir = store.overlay_dir or (store.data_dir / "writeback")

    # ------------------------------------------------------------ 표현식

    def _helpers(self, ctx: dict) -> dict:
        from ontoquant.core import action_functions as af
        return {
            "len": len, "abs": abs, "min": min, "max": max, "None": None,
            "evaluation_passed": lambda run_id: af.evaluation_passed(self.store, run_id),
            "would_breach_limits": lambda proposal: af.would_breach_limits(self.store, proposal),
            "passed_eval_count": lambda mv_id: af.passed_eval_count_helper(self.store, mv_id),
            "all_instruments_exist": lambda legs: af.all_instruments_exist(self.store, legs),
            "abs_weight_delta_sum": af.abs_weight_delta_sum,
        }

    def _eval(self, expr: str, ctx: dict) -> Any:
        ns = {**self._helpers(ctx)}
        for k, v in ctx.items():
            if k in ("params",) or isinstance(v, (dict, type(None))):
                ns[k] = AttrView(v) if isinstance(v, (dict, type(None))) else v
            else:
                ns[k] = v
        ns["params"] = AttrView(ctx.get("params", {}))
        return eval(expr, {"__builtins__": {}}, ns)  # noqa: S307 — 레포 소유 스키마 전용

    # ------------------------------------------------------------ 값 해석

    def _resolve_value(self, v: Any, ctx: dict) -> Any:
        if isinstance(v, str) and v.startswith("$"):
            if v == "$now":
                return datetime.now(timezone.utc).isoformat(timespec="seconds")
            if v == "$today":
                return str(date.today())
            if v == "$actor":
                return self.actor
            if v.startswith("$param."):
                return ctx["params"].get(v[len("$param."):])
            if v.startswith("$created."):
                return ctx["created"].get(v[len("$created."):])
            if v.startswith("$generateId(") and v.endswith(")"):
                return audit.new_id(v[len("$generateId("):-1])
            if v.startswith("$snapshot(") and v.endswith(")"):
                name = v[len("$snapshot("):-1]
                obj = ctx.get(name)
                snap = dict(obj) if isinstance(obj, dict) else {}
                run_id = snap.get("backtestRunId")
                if run_id:
                    run = self.store.get("EvaluationRun", run_id)
                    if run:
                        snap["backtestMetrics"] = run.get("metricSet")
                        snap["backtestPassedGates"] = run.get("passedGates")
                return snap
            if v.startswith("$expr(") and v.endswith(")"):
                return self._eval(v[len("$expr("):-1], ctx)
            raise ValueError(f"알 수 없는 템플릿: {v}")
        if isinstance(v, dict):
            return {k: self._resolve_value(x, ctx) for k, x in v.items()}
        if isinstance(v, list):
            return [self._resolve_value(x, ctx) for x in v]
        return v

    # ------------------------------------------------------------ 제출

    def submit(self, action_api_name: str, params: dict) -> dict:
        at: ActionTypeDef | None = self.store.schema.actionTypes.get(action_api_name)
        if at is None:
            raise KeyError(f"알 수 없는 액션 타입: {action_api_name}")

        # ① 파라미터
        resolved: dict[str, Any] = {}
        ctx: dict[str, Any] = {"params": resolved, "created": {}}
        for name, p in at.parameters.items():
            val = params.get(name, p.default)
            if val is None and p.required:
                raise ValueError(f"필수 파라미터 누락: {name}")
            if val is not None and p.enum and val not in p.enum:
                raise ValueError(f"{name}: '{val}' 는 enum {p.enum} 에 없음")
            if val is not None and p.minLength and isinstance(val, str) and len(val) < p.minLength:
                raise ValueError(f"{name}: 최소 {p.minLength}자 필요")
            resolved[name] = val
            if p.type == "objectRef" and p.bind:
                ctx[p.bind] = self.store.get(p.objectType, val) if val is not None else None

        # ② 제출 기준
        failures: list[str] = []
        criteria_results = []
        for c in at.submissionCriteria:
            try:
                ok = bool(self._eval(c.condition, ctx))
            except Exception as exc:  # noqa: BLE001
                ok = False
                failures.append(f"{c.failureMessage} (평가 오류: {exc})")
                criteria_results.append({"condition": c.condition, "passed": False, "error": str(exc)})
                continue
            criteria_results.append({"condition": c.condition, "passed": ok})
            if not ok:
                failures.append(c.failureMessage)
        if failures:
            audit.log_action(action_api_name, params, self.actor, "REJECTED_CRITERIA",
                             criteria_results=criteria_results,
                             overlay_dir=self._log_dir)
            return {"ok": False, "failures": failures}

        # ③ 규칙 (스테이징 → 일괄 커밋)
        batch = WriteBatch()
        ctx["batch"] = batch
        try:
            for rule in at.rules:
                if rule.when and not bool(self._eval(rule.when, ctx)):
                    continue
                if rule.type == "createObject":
                    values = self._resolve_value(rule.values or {}, ctx)
                    values = {k: v for k, v in values.items() if v is not None}
                    pk_field = self.store.schema.objectTypes[rule.objectType].primaryKey
                    batch.upsert("writeback", rule.objectType, values)
                    ctx["created"][rule.objectType] = values[pk_field]
                    ctx[rule.objectType[0].lower() + rule.objectType[1:]] = values
                elif rule.type == "modifyObject":
                    pk = self._resolve_value(rule.target, ctx)
                    current = self.store.get(rule.objectType, pk) or {}
                    updates = self._resolve_value(rule.set or {}, ctx)
                    pk_field = self.store.schema.objectTypes[rule.objectType].primaryKey
                    batch.upsert("writeback", rule.objectType,
                                 {**current, **updates, pk_field: pk})
                elif rule.type == "createLink":
                    lt = self.store.schema.linkTypes[rule.linkType]
                    from_pk = self._resolve_value(rule.from_, ctx)
                    from_type = self._concrete_type(lt.from_, from_pk, ctx)
                    targets = (self._resolve_value(rule.toEach, ctx) or []) if rule.toEach \
                        else [self._resolve_value(rule.to, ctx)]
                    for to_pk in targets:
                        if to_pk is None:
                            continue
                        to_type = self._concrete_type(lt.to, to_pk, ctx)
                        batch.link("writeback", LinkRecord(rule.linkType, from_type, from_pk,
                                                           to_type, to_pk))
                elif rule.type == "functionRule":
                    fn = FUNCTION_REGISTRY.get(rule.function)
                    if fn is None:
                        raise KeyError(f"등록되지 않은 함수 규칙: {rule.function}")
                    fn(self.store, ctx)
                else:
                    raise ValueError(f"미지원 규칙 타입: {rule.type}")
        except Exception as exc:
            audit.log_action(action_api_name, params, self.actor, "FAILED",
                             criteria_results=criteria_results, detail=str(exc),
                             overlay_dir=self._log_dir)
            raise

        changed = batch.apply(self.store, self.overlay)

        # ④ 사이드 이펙트
        entry = audit.log_action(action_api_name, params, self.actor, "SUBMITTED",
                                 criteria_results=criteria_results, objects_changed=changed,
                                 overlay_dir=self._log_dir)
        for se in at.sideEffects:
            if se.type == "notification" and not self.overlay:
                self._notify(se.template or action_api_name, ctx)
        return {"ok": True, "changed": changed, "created": ctx["created"],
                "actionLogId": entry["actionLogId"]}

    def _concrete_type(self, endpoint: str, pk: str, ctx: dict) -> str:
        types = self.store.schema.resolve_types(endpoint)
        if len(types) == 1:
            return types[0]
        actual = self.store.get_type_of(pk, types)
        if actual:
            return actual
        for t in types:
            if ctx["created"].get(t) == pk:
                return t
        raise ValueError(f"{endpoint} 인터페이스에서 {pk} 의 구체 타입을 찾을 수 없음")

    def _notify(self, template: str, ctx: dict) -> None:
        try:
            msg = template
            for key, obj in ctx.items():
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        msg = msg.replace(f"{{{key}.{k}}}", str(v))
            path = self.store.data_dir / "writeback" / "notifications.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "message": msg,
                }, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — 알림 실패는 액션을 막지 않는다
            pass
