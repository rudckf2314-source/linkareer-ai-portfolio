"""실시간 최신 링커리어 기업분석 자료 매칭 — 대시보드·기업분석 탭 연동."""
from __future__ import annotations

import logging

from core.company_analysis_catalog import suggest_related_searches
from core.company_analysis_matcher import (
    build_corporate_analysis_payload,
    rank_company_analysis_candidates,
)
from services.matching_orchestrator import matching_orchestrator
from tools.tavily_tool import tavily_tool

logger = logging.getLogger(__name__)


class CompanyAnalysisService:
    """분야·직무·기업 인풋 → 최신 기업분석 뷰어 URL 1건 매칭."""

    def _collect_candidates(self, target_company: str) -> list[dict]:
        company = (target_company or "").strip()
        if not company:
            return []

        queries = [
            f"site:linkareer.com/company-analysis {company} 기업분석",
            f"site:linkareer.com/company-analysis {company} 기업분석자료",
        ]
        seen: set[str] = set()
        out: list[dict] = []
        for q in queries:
            for item in tavily_tool.search_linkareer_company_analysis(q, max_results=25):
                url = item.get("url") or item.get("link") or ""
                if url in seen:
                    continue
                seen.add(url)
                out.append(item)
        return out

    def match_latest(
        self,
        *,
        target_company: str,
        target_job: str = "",
        target_field: str = "",
    ) -> dict:
        """최신 기업분석 1건 매칭 + 정형 JSON 반환."""
        company = (target_company or "").strip()
        job = (target_job or "").strip()
        field = (target_field or "").strip()

        raw_items = self._collect_candidates(company)
        ranked = rank_company_analysis_candidates(
            raw_items,
            target_company=company,
            target_field=field,
            target_job=job,
        )

        # matching_orchestrator 경유 — 정제/매칭 파이프라인과 동일 스택
        if ranked:
            orchestrated = matching_orchestrator.route_company_analysis_match(
                [
                    {
                        "title": c.title,
                        "url": c.url,
                        "snippet": c.snippet,
                        "company_score": c.company_score,
                        "match_type": c.match_type,
                    }
                    for c in ranked
                ],
                target_company=company,
                target_field=field,
                target_job=job,
            )
            best_key = None
            if orchestrated.get("items"):
                best_key = orchestrated["items"][0].get("url")
            top = next((c for c in ranked if c.url == best_key), ranked[0])
        else:
            top = None

        payload = build_corporate_analysis_payload(
            top,
            target_company=company,
            target_job=job,
            target_field=field,
        )
        payload["related_searches"] = suggest_related_searches(company)
        logger.info(
            "[CompanyAnalysis] company=%s matched=%s url=%s",
            company,
            payload["corporate_analysis_content"].get("has_data"),
            payload["corporate_analysis_content"].get("target_viewer_url", "")[:60],
        )
        return payload

    def suggest(self, query: str = "", limit: int = 8) -> list[str]:
        return suggest_related_searches(query, limit=limit)


company_analysis_service = CompanyAnalysisService()
