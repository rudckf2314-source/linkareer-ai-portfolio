"""
[Validate_Matching_Score] 분야→직무→기업 3단계 파라미터 기반 50:30:20 유사도 검증.

에이전트 재사용 원칙: 수학적 스코어링은 본 모듈(결정론)에서 수행하고,
jd_structural_analyzer 에는 동일 룰의 시스템 프롬프트만 서브 태스크로 주입합니다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.recommendation_engine import UserRecommendContext

_META_PATH = Path(__file__).resolve().parent.parent / "cache" / "recommendation_meta.json"

# 에이전트 주입용 시스템 프롬프트 (jd_structural_analyzer 서브 태스크와 동기화)
VALIDATOR_SYSTEM_PROMPT = """
Role: 커리어 데이터 맥락 신뢰도 검증관 (Contextual Match Validator)
Context_Rule:
  - 유저 인풋 계층 [1단계: 분야, 2단계: 직무, 3단계: 기업]과 수집 데이터 간 유사성을 정량 검증합니다.
Scoring_Formula:
  - 최종 매칭 점수는 100점 만점: Score = (Job_Score * 0.50) + (Industry_Score * 0.30) + (Company_Score * 0.20)
Evaluation_Protocol:
  1. 직무 유사도 (50%): 희망 직무 역량 벡터와 공고/자소서 본문 맥락 일치. Job_Score < 20 이면 Hard Drop.
  2. 분야 유사도 (30%): 희망 분야 도메인과 콘텐츠 비즈니스 연관성.
  3. 기업 유사도 (20%): 타겟 기업 일치 시 Company_Score 만점. 동급 피어 대체 시 lock-in 방지로 15점 내외 인정.
Output_Format:
  - 통과 항목에 final_matching_score, score_breakdown, dynamic_reason_phrase 를 반드시 포함합니다.
Company_Analysis_Extension:
  - 링커리어 기업분석 자료 매칭 시 계열사 Strict Match(예: 삼성전자(DS)) 우선, 없으면 모기업 Parent Fallback.
  - 동일 기업 후보 중 archive_title의 연도·반기(2026 상반기 > 2025 하반기) 최신본 1건만 선택합니다.
""".strip()


def _load_validation_rules() -> dict:
    defaults = {
        "weights": {"job": 0.50, "industry": 0.30, "company": 0.20},
        "job_hard_drop_min": 20,
        "peer_company_score_cap": 75,
        "min_final_score": 28,
    }
    if _META_PATH.is_file():
        try:
            meta = json.loads(_META_PATH.read_text(encoding="utf-8"))
            return {**defaults, **(meta.get("validation_rules") or {})}
        except Exception:
            pass
    return defaults


def _norm_company(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").lower())


def _is_exact_company_match(item: dict, ctx: UserRecommendContext) -> bool:
    target = _norm_company(ctx.company_query)
    if not target:
        return False
    candidates = [
        item.get("company", ""),
        item.get("title", ""),
        item.get("snippet", ""),
    ]
    for c in candidates:
        if target in _norm_company(str(c)):
            return True
    return False


def _to_century(sim: float) -> float:
    return round(max(0.0, min(1.0, float(sim or 0))) * 100, 2)


def _dynamic_reason_phrase(
    item: dict,
    ctx: UserRecommendContext,
    *,
    exact_company: bool,
    is_peer_substitute: bool,
    fallback_level: int,
) -> str:
    item_co = (item.get("company") or "").strip() or "해당 기업"
    user_co = (ctx.company_query or "").strip()
    user_job = (ctx.job_query or "").strip()

    if exact_company and user_co:
        return f"선택하신 **{user_co}**의 **{user_job}** 관련 데이터입니다."
    if is_peer_substitute or fallback_level >= 2:
        if user_co:
            return (
                f"**{user_co}**의 라이브 데이터가 제한되어, 동일 직무(**{user_job}**)를 채용하는 "
                f"**{item_co}**의 대안 데이터를 큐레이션했습니다."
            )
        return f"동일 직무(**{user_job}**) 맥락의 **{item_co}** 대안 데이터입니다."
    if fallback_level == 1:
        return f"**{ctx.field_query}** 분야 · **{user_job}** 직무 기준으로 매칭된 콘텐츠입니다."
    return f"**{user_job}** 직무 역량 중심 유동 매칭 결과입니다."


def validate_matching_score(
    item: dict,
    ctx: UserRecommendContext,
    *,
    fallback_level: int = 0,
    is_peer_substitute: bool = False,
) -> dict:
    """
    Validate_Matching_Score 태스크 — 단일 항목 100점 스케일 검증·강화.

    Returns enriched item; validation_passed=False 이면 Hard Drop 대상.
    """
    rules = _load_validation_rules()
    w = rules.get("weights") or {}
    w_job = float(w.get("job", 0.50))
    w_ind = float(w.get("industry", 0.30))
    w_co = float(w.get("company", 0.20))
    job_drop_min = float(rules.get("job_hard_drop_min", 20))
    peer_cap = float(rules.get("peer_company_score_cap", 75))

    raw = item.get("_raw_similarity") or {}
    job_raw = float(raw.get("job") or 0)
    domain_raw = float(raw.get("domain") or 0)
    company_raw = float(raw.get("company") or 0)

    job_score = _to_century(job_raw)
    industry_score = _to_century(domain_raw)
    exact_company = _is_exact_company_match(item, ctx)

    if exact_company:
        company_score = 100.0
    elif is_peer_substitute or fallback_level >= 2:
        company_score = min(_to_century(company_raw), peer_cap)
    else:
        company_score = _to_century(company_raw)

    final = round(
        job_score * w_job + industry_score * w_ind + company_score * w_co,
        2,
    )
    passed = job_score >= job_drop_min

    breakdown = {
        "job_score": job_score,
        "industry_score": industry_score,
        "company_score": company_score,
        "job_weighted": round(job_score * w_job, 2),
        "industry_weighted": round(industry_score * w_ind, 2),
        "company_weighted": round(company_score * w_co, 2),
    }

    reason = _dynamic_reason_phrase(
        item,
        ctx,
        exact_company=exact_company,
        is_peer_substitute=is_peer_substitute or fallback_level >= 2,
        fallback_level=fallback_level,
    )

    enriched = {
        **item,
        "final_matching_score": final,
        "score_breakdown_100": breakdown,
        "matching_score": round(final / 100, 4),
        "score_breakdown": {
            "job_role_score": round(breakdown["job_weighted"] / 100, 4),
            "industry_domain_score": round(breakdown["industry_weighted"] / 100, 4),
            "company_match_score": round(breakdown["company_weighted"] / 100, 4),
        },
        "dynamic_reason_phrase": reason,
        "validation_passed": passed,
        "validation_meta": {
            "exact_company_match": exact_company,
            "is_peer_substitute": bool(is_peer_substitute or fallback_level >= 2),
            "fallback_level": fallback_level,
            "job_hard_drop_min": job_drop_min,
            "formula": "50:30:20",
        },
    }
    return enriched


def validate_matching_batch(
    items: list[dict],
    ctx: UserRecommendContext,
    *,
    fallback_level: int = 0,
    is_peer_substitute: bool = False,
    drop_failed: bool = True,
) -> list[dict]:
    """배치 검증 — Hard Drop 적용 후 final_matching_score 내림차순."""
    rules = _load_validation_rules()
    min_final = float(rules.get("min_final_score", 28))

    out: list[dict] = []
    for it in items or []:
        v = validate_matching_score(
            it,
            ctx,
            fallback_level=fallback_level,
            is_peer_substitute=is_peer_substitute,
        )
        if drop_failed and not v.get("validation_passed"):
            continue
        if drop_failed and float(v.get("final_matching_score") or 0) < min_final:
            if float((v.get("_raw_similarity") or {}).get("job") or 0) < 0.35:
                continue
        out.append(v)

    out.sort(key=lambda x: -(x.get("final_matching_score") or 0))
    return out
