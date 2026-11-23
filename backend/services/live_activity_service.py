"""D-Day 필터 + 직무/분야 Fallback 라우팅 서비스."""
from __future__ import annotations

from core.relevance_gate import score_and_filter
from core.d_day_engine import drop_expired, filter_live_recommendations, sort_by_urgency
from services.recommendation_engine import UserRecommendContext, recommendation_engine


class LiveActivityService:
    """공모전·인턴 라이브 공고 파이프라인 (D+ Drop → 스코어 → 임박순)."""

    MIN_LIVE = 3

    def process_pool(
        self,
        items: list[dict],
        ctx: UserRecommendContext,
        *,
        kind: str = "activity",
        min_required: int | None = None,
    ) -> dict:
        min_req = min_required or self.MIN_LIVE

        # 1) D+ Drop + 임박순 1차
        live, d_meta = filter_live_recommendations(items, min_required=min_req)

        # 2) 직무>분야 동적 스코어 + 관련성 게이트 (무관 공고 Drop)
        gate_opts: dict = {}
        if kind == "공모전":
            # 공모전 제목에 직무명이 없는 경우가 많음 — 링커리어 IT/SW 풀 우선 통과
            gate_opts = {"require_token": False, "min_matching": 0.10, "min_job": 0.08}
        elif kind in ("인턴", "인턴십"):
            gate_opts = {"require_token": False, "min_matching": 0.10, "min_job": 0.08}

        scored_live = score_and_filter(
            [{**it, "category": kind, "kind": kind} for it in live],
            ctx,
            limit=max(min_req * 6, 30),
            **gate_opts,
        )

        # 링커리어 공모전 최소 2건 보존 (관련성 게이트 탈락 방지)
        if kind == "공모전":
            scored_live = self._merge_linkareer_contests(scored_live, live, min_keep=2)
        elif kind in ("인턴", "인턴십"):
            scored_live = self._merge_field_interns(scored_live, live, ctx, min_keep=5)

        # 3) Fallback: 유효 live 부족 시 스코어 상위로 채움 (이미 live만 대상)
        needs_fallback = d_meta.get("needs_fallback", False) or (
            kind in ("인턴", "인턴십") and len(scored_live) < min_req
        )
        fallback_level = 0
        fallback_message = ""

        if needs_fallback and scored_live:
            fb_limit = 16 if kind in ("인턴", "인턴십") else 12
            fb = recommendation_engine.select_with_fallback(scored_live, ctx, limit=fb_limit)
            scored_live = fb.get("items") or scored_live
            fallback_level = fb.get("fallback_level", 0)
            if fb.get("is_fallback"):
                fallback_message = (
                    fb.get("fallback_message")
                    or "마감된 공고를 제외한 뒤, 직무·분야 기준으로 유효 라이브 공고를 대체 매칭했습니다."
                )

        # 4) 최종: 임박순 우선 (동일 urgency 내 matching_score)
        final = sort_by_urgency(scored_live)

        return {
            "items": final,
            "d_day_meta": d_meta,
            "needs_fallback": needs_fallback,
            "fallback_level": fallback_level,
            "fallback_message": fallback_message,
            "recommendation_context": {
                "focus_priority": ["job_role", "industry_domain", "company_match"],
                "is_lock_in_prevented": True,
                "user_job": ctx.job,
                "user_field": ctx.field,
                "user_company": ctx.company,
                "relevance_gated": True,
                "validation_formula": "50:30:20",
            },
        }

    @staticmethod
    def _merge_linkareer_contests(
        scored: list[dict],
        live: list[dict],
        *,
        min_keep: int = 2,
    ) -> list[dict]:
        """링커리어 IT/SW 공모전 최소 건수 보존."""
        linkareer_live = [it for it in live if _is_linkareer_item(it)]
        if not linkareer_live:
            return scored

        seen = {it.get("link_url") or it.get("title") for it in scored}
        merged = list(scored)
        for it in linkareer_live:
            key = it.get("link_url") or it.get("title")
            if key in seen:
                continue
            seen.add(key)
            merged.append(it)
            if sum(1 for x in merged if _is_linkareer_item(x)) >= min_keep:
                break
        return merged

    @staticmethod
    def _merge_field_interns(
        scored: list[dict],
        live: list[dict],
        ctx: UserRecommendContext,
        *,
        min_keep: int = 5,
    ) -> list[dict]:
        """분야·직무 토큰이 겹치는 인턴 공고 최소 건수 보존."""
        from core.relevance_gate import has_context_token_overlap

        field_hits = [it for it in live if has_context_token_overlap(it, ctx)]
        if not field_hits:
            return scored

        current_field_hits = sum(1 for it in scored if has_context_token_overlap(it, ctx))
        if current_field_hits >= min_keep:
            return scored

        seen = {it.get("link_url") or it.get("title") for it in scored}
        merged = list(scored)
        for it in field_hits:
            key = it.get("link_url") or it.get("title")
            if key in seen:
                continue
            seen.add(key)
            merged.append(it)
            current_field_hits = sum(1 for x in merged if has_context_token_overlap(x, ctx))
            if current_field_hits >= min_keep:
                break
        return merged


live_activity_service = LiveActivityService()


def _is_linkareer_item(item: dict) -> bool:
    plat = str(item.get("source_platform") or "")
    url = str(item.get("link_url") or item.get("link") or "").lower()
    return "링커리어" in plat or "linkareer.com" in url
