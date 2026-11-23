"""
[Relevance Gate] 직무·분야·기업 맥락 무관 항목 Drop + Validate_Matching_Score 연동.

크롤 풀·추천 결과에서 matching_score / 키워드 겹침 미달 시 UI 노출 차단.
직무 유사도 Job_Score < 20 (100점 척도) 시 Hard Drop.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.recommendation_engine import UserRecommendContext

_META_PATH = Path(__file__).resolve().parent.parent / "cache" / "recommendation_meta.json"

_STOP = frozenset({
    "및", "등", "신입", "경력", "채용", "모집", "공고", "인턴", "인턴십",
    "상시", "수시", "년", "월", "일", "주", "the", "and", "for",
})


def _load_rules() -> dict:
    defaults = {
        "min_matching_score": 0.28,
        "min_job_similarity": 0.22,
        "min_domain_similarity": 0.18,
        "tier3_min_job_similarity": 0.25,
        "require_title_token_match": True,
        "job_hard_drop_min": 20,
    }
    if _META_PATH.is_file():
        try:
            meta = json.loads(_META_PATH.read_text(encoding="utf-8"))
            rel = meta.get("relevance_rules") or {}
            val = meta.get("validation_rules") or {}
            return {**defaults, **rel, **{k: v for k, v in val.items() if k == "job_hard_drop_min"}}
        except Exception:
            pass
    return defaults


def _tokens(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"[\w가-힣]{2,}", text or "")
        if t.lower() not in _STOP
    }


def _item_text(item: dict) -> str:
    return " ".join(filter(None, [
        item.get("title", ""),
        item.get("company", ""),
        item.get("snippet", ""),
        item.get("keyword_match", ""),
    ])).strip()


def _context_tokens(ctx: UserRecommendContext) -> set[str]:
    parts = [ctx.job, ctx.field, ctx.company, *ctx.extra_keywords]
    out: set[str] = set()
    for p in parts:
        out |= _tokens(p)
    return out


def has_context_token_overlap(item: dict, ctx: UserRecommendContext) -> bool:
    """제목·스니펫에 직무/분야/기업 토큰이 하나라도 포함되는지."""
    blob = _item_text(item).lower()
    for tok in _context_tokens(ctx):
        if len(tok) >= 2 and tok in blob:
            return True
    return False


def score_and_filter(
    items: list[dict],
    ctx: UserRecommendContext,
    *,
    min_matching: float | None = None,
    min_job: float | None = None,
    require_token: bool | None = None,
    limit: int = 20,
    fallback_level: int = 0,
    is_peer_substitute: bool = False,
) -> list[dict]:
    """스코어 산출 → Validate_Matching_Score → 관련성 미달 Hard Drop."""
    from services.matching_orchestrator import matching_orchestrator

    result = matching_orchestrator.route_validate_matching_score(
        items or [],
        ctx,
        fallback_level=fallback_level,
        is_peer_substitute=is_peer_substitute,
        limit=limit * 2,
    )
    validated = result.get("items") or []

    rules = _load_rules()
    min_match = min_matching if min_matching is not None else float(rules["min_matching_score"])
    min_job_sim = min_job if min_job is not None else float(rules["min_job_similarity"])
    token_req = require_token if require_token is not None else bool(rules["require_title_token_match"])

    scored: list[dict] = []
    for s in validated:
        raw = s.get("_raw_similarity") or {}
        job_sim = float(raw.get("job") or 0)
        match = float(s.get("matching_score") or 0)

        if not s.get("validation_passed", True):
            continue
        if match < min_match and job_sim < min_job_sim:
            continue
        if token_req and not has_context_token_overlap(s, ctx) and job_sim < 0.35:
            continue
        scored.append(s)

    scored.sort(key=lambda x: -(x.get("final_matching_score") or x.get("matching_score") or 0))
    return scored[:limit]


def filter_fallback_tier3(items: list[dict], ctx: UserRecommendContext) -> list[dict]:
    """3단계 폴백에서도 직무 유사도 하한 + Validate_Matching_Score 적용."""
    from core.matching_validator import validate_matching_batch

    rules = _load_rules()
    floor = float(rules.get("tier3_min_job_similarity", 0.25))
    min_match = float(rules["min_matching_score"])
    job_drop = float(rules.get("job_hard_drop_min", 20))

    pre: list[dict] = []
    for it in items or []:
        raw = it.get("_raw_similarity") or {}
        job_sim = float(raw.get("job") or 0)
        match = float(it.get("matching_score") or 0)
        if job_sim < floor and match < min_match:
            continue
        if not has_context_token_overlap(it, ctx) and job_sim < 0.32:
            continue
        pre.append(it)

    validated = validate_matching_batch(
        pre,
        ctx,
        fallback_level=3,
        is_peer_substitute=True,
    )
    return [v for v in validated if float((v.get("score_breakdown_100") or {}).get("job_score") or 0) >= job_drop]
