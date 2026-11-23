"""합격 자소서 스케일다운 — 임베딩 기반 동적 추천 엔진 연동."""
from __future__ import annotations

from core.relevance_gate import score_and_filter
from services.recommendation_engine import UserRecommendContext, recommendation_engine
from tools.cover_letter_crawler_tool import cover_letter_crawler_tool


def format_for_agent(result: dict) -> str:
    lines = [
        f"[검색 단계] fallback_level={result.get('fallback_level', 1)} "
        f"is_fallback={result.get('is_fallback', False)}",
    ]
    ctx = result.get("recommendation_context") or {}
    if ctx.get("focus_priority"):
        lines.append(f"[매칭 우선순위] {' > '.join(ctx['focus_priority'])}")
    if result.get("fallback_message"):
        lines.append(f"[안내] {result['fallback_message']}")
    for item in result.get("items", [])[:15]:
        final = item.get("final_matching_score", item.get("matching_score", ""))
        badge = item.get("dynamic_badge", "")
        reason = item.get("dynamic_reason_phrase", "")
        bd = item.get("score_breakdown_100") or {}
        breakdown_line = ""
        if bd:
            breakdown_line = (
                f" [J:{bd.get('job_score','-')} I:{bd.get('industry_score','-')} "
                f"C:{bd.get('company_score','-')}]"
            )
        lines.append(
            f"[{item.get('source_platform')}] {item.get('title')} "
            f"(score:{final}{breakdown_line} {badge})\n"
            f"기업:{item.get('company','')} URL: {item.get('url')}\n"
        )
        if reason:
            lines.append(f"안내: {reason}\n")
        lines.append(
            f"본문: {(item.get('content') or item.get('snippet') or '')[:1500]}\n"
        )
    return "\n".join(lines) if len(lines) > 1 else "(합격 자소서 수집 없음)"


class CoverLetterService:
    """임베딩 스코어 기반 3단계 스케일다운 (직무+기업 → 직무+분야 → 직무)."""

    def search_with_fallback(
        self,
        *,
        target_field: str,
        target_company: str,
        target_job: str,
    ) -> dict:
        pool = cover_letter_crawler_tool.fetch_pool(
            company=target_company,
            job=target_job,
            scrape_details=True,
        )
        ctx = UserRecommendContext(
            job=target_job,
            field=target_field,
            company=target_company,
        )
        gated = score_and_filter(pool, ctx, limit=30)
        if not gated:
            return {
                "items": [],
                "count": 0,
                "is_fallback": True,
                "fallback_level": 3,
                "fallback_message": (
                    f"[{target_company}] [{target_job}]와 관련성이 충분한 합격 자소서를 "
                    "찾지 못했습니다. 키워드·타겟 기업을 확인해 주세요."
                ),
                "reference_links": [],
            }
        return recommendation_engine.select_with_fallback(gated, ctx, limit=15)

    def enrich_benchmark_output(self, benchmark: dict, search_result: dict) -> dict:
        out = dict(benchmark or {})
        out["is_fallback"] = search_result.get("is_fallback", False)
        out["fallback_level"] = search_result.get("fallback_level", 1)
        if search_result.get("fallback_message"):
            out["fallback_message"] = search_result["fallback_message"]
        if search_result.get("recommendation_context"):
            out["recommendation_context"] = search_result["recommendation_context"]

        existing = {
            r.get("url") for r in (out.get("reference_links") or [])
            if isinstance(r, dict) and r.get("url")
        }
        merged_refs = list(out.get("reference_links") or [])
        for ref in search_result.get("reference_links") or []:
            if ref.get("url") and ref["url"] not in existing:
                merged_refs.append(ref)
                existing.add(ref["url"])
        if merged_refs:
            out["reference_links"] = merged_refs
        count = search_result.get("count", 0) or len(search_result.get("items") or [])
        out.setdefault("source_meta", {})
        out["source_meta"]["cover_letter_count"] = count
        out["source_meta"]["fallback_level"] = search_result.get("fallback_level")
        out["source_meta"]["is_fallback"] = search_result.get("is_fallback", False)
        return out


cover_letter_service = CoverLetterService()
