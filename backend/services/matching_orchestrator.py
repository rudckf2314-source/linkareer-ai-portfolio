"""
[Matching Orchestrator] Validate_Matching_Score 태스크 라우팅.

기존 텍스트 분석 에이전트(jd_structural_analyzer)가 존재하므로
신규 Validation Agent 생성 없이 recommendation_engine + matching_validator 스택을 재사용합니다.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.matching_validator import VALIDATOR_SYSTEM_PROMPT, validate_matching_batch
from services.recommendation_engine import UserRecommendContext, recommendation_engine

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# 라우팅 결정: 기존 임베딩 스코어링 스택 재사용 (우선순위 1)
_REUSE_EXISTING_STACK = True


class MatchingOrchestrator:
    """Validate_Matching_Score 트리거 시 스코어링·검증 파이프라인 오케스트레이션."""

    def route_validate_matching_score(
        self,
        items: list[dict],
        ctx: UserRecommendContext,
        *,
        fallback_level: int = 0,
        is_peer_substitute: bool = False,
        limit: int = 20,
    ) -> dict:
        """
        1) recommendation_engine.score_item (50:30:20 임베딩)
        2) matching_validator.validate_matching_batch (100점 검증 + Hard Drop)
        """
        if not items:
            return {
                "items": [],
                "count": 0,
                "routing": "reuse_recommendation_stack",
                "validator_prompt": VALIDATOR_SYSTEM_PROMPT[:120] + "...",
            }

        scored = [recommendation_engine.score_item(it, ctx) for it in items]
        validated = validate_matching_batch(
            scored,
            ctx,
            fallback_level=fallback_level,
            is_peer_substitute=is_peer_substitute,
            drop_failed=True,
        )[:limit]

        logger.info(
            "[MatchingOrchestrator] Validate_Matching_Score items=%d passed=%d fallback=%d peer=%s",
            len(items),
            len(validated),
            fallback_level,
            is_peer_substitute,
        )

        return {
            "items": validated,
            "count": len(validated),
            "routing": "reuse_recommendation_stack" if _REUSE_EXISTING_STACK else "validation_agent",
            "assigned_agent": "jd_structural_analyzer (prompt extension)" if _REUSE_EXISTING_STACK else "validation_agent",
            "formula": "50:30:20",
        }

    def route_company_analysis_match(
        self,
        items: list[dict],
        *,
        target_company: str,
        target_field: str = "",
        target_job: str = "",
    ) -> dict:
        """
        기업분석 자료 Strict/Fallback 매칭 — 정제·매칭 에이전트 규칙 적용.
        계열사 정확 일치 우선, 없으면 모기업 Fallback.
        """
        from core.company_analysis_matcher import rank_company_analysis_candidates

        ranked = rank_company_analysis_candidates(
            items,
            target_company=target_company,
            target_field=target_field,
            target_job=target_job,
        )
        out = [
            {
                "title": c.title,
                "url": c.url,
                "snippet": c.snippet,
                "company_match_score": c.company_score,
                "match_type": c.match_type,
                "is_latest": c.is_latest,
                "period_year": c.period_year,
                "period_half": c.period_half,
            }
            for c in ranked
        ]
        logger.info(
            "[MatchingOrchestrator] company_analysis company=%s candidates=%d top=%s",
            target_company,
            len(out),
            out[0]["match_type"] if out else "none",
        )
        return {
            "items": out[:1],
            "count": len(out[:1]),
            "routing": "company_analysis_matcher",
            "assigned_agent": "matching_validator (company analysis extension)",
            "formula": "strict>parent_fallback>brand_partial + latest_period",
        }


matching_orchestrator = MatchingOrchestrator()
