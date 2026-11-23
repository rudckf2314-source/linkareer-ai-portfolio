"""[Infrastructure Tool Layer] Serper 기반 사람인 트래킹 + Tavily Fallback 도구."""
from typing import Any

import requests

from core.config import settings
from tools.base_tool import BaseTool
from tools.tavily_tool import tavily_tool


class SaraminError(Exception):
    """사람인 검색 인프라 오류 (라우터에서 HTTP 매핑)."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class SaraminTool(BaseTool):
    """
    Serper(Google Search) API로 사람인 채용공고를 트래킹하고,
    실패/제한 시 TavilyTool 폴백으로 결합한다.
    """

    name = "saramin_tool"

    def __init__(self) -> None:
        self._serper_key = settings.SERPER_API_KEY
        self._tavily = tavily_tool

    @staticmethod
    def build_query(keyword: str) -> str:
        return f"site:saramin.co.kr {keyword.strip()} 채용공고"

    def _serper_search(self, query: str) -> list[dict]:
        if not self._serper_key:
            return []
        try:
            response = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self._serper_key, "Content-Type": "application/json"},
                json={"q": query, "num": 20, "gl": "kr", "hl": "ko"},
                timeout=15,
            )
        except Exception as e:  # noqa: BLE001
            raise SaraminError(f"Serper API 호출 실패: {str(e)}")

        if response.ok:
            jobs = []
            for item in response.json().get("organic", []):
                link = item.get("link", "")
                if "saramin.co.kr" not in link:
                    continue
                jobs.append({
                    "title": item.get("title", "").strip(),
                    "link": link,
                    "snippet": item.get("snippet", "").strip(),
                })
            return jobs
        # 400(보통 무료계정 site: 제한)은 폴백, 그 외는 오류
        if response.status_code != 400:
            raise SaraminError(f"Serper API 오류: {response.text[:200]}")
        return []

    def _strict_filter(self, jobs: list[dict], keyword: str) -> list[dict]:
        tokens = [t.strip().lower() for t in keyword.split() if len(t.strip()) >= 2]
        if not tokens:
            return jobs
        skip = {"인턴", "인턴십", "채용", "채용공고", "공고", "모집", "신입"}
        core = [t for t in tokens if t not in skip]
        if not core:
            return jobs

        filtered = []
        for job in jobs:
            text = (job.get("title", "") + " " + job.get("snippet", "")).lower()
            if any(t in text for t in core):
                filtered.append(job)
        return filtered

    def execute(self, query: str, **kwargs: Any) -> list[dict]:
        """키워드로 사람인 채용공고 검색. Serper → Tavily 폴백."""
        keyword = query.strip()
        
        from services.vector_cache_service import vector_cache_service
        
        # 1. 벡터 DB 캐시 조회
        cached = vector_cache_service.query_activities(keyword, threshold=1.0)
        saramin_cached = [c for c in cached if c.get("source_platform") == "사람인"]
        if len(saramin_cached) >= 3:
            jobs = [{"title": c["title"], "link": c["link_url"], "snippet": c["snippet"]} for c in saramin_cached]
            filtered = self._strict_filter(jobs, keyword)
            if len(filtered) >= 3:
                return filtered
            
        # 2. 캐시 미스 또는 필터링 후 부족 시 실시간 검색
        jobs = self._serper_search(self.build_query(keyword))
        if not jobs:
            if not settings.TAVILY_API_KEY:
                raise SaraminError(
                    "검색 API를 사용할 수 없습니다. SERPER_API_KEY 또는 TAVILY_API_KEY를 확인해 주세요.",
                    status_code=500,
                )
            jobs = self._tavily.search_saramin_fallback(keyword)
            
        # 엄격한 키워드 필터링 적용 (타 기업 공고 노출 방지)
        jobs = self._strict_filter(jobs, keyword)
            
        # 3. 벡터 DB에 결과 캐싱
        if jobs:
            vector_cache_service.cache_activities(jobs, "사람인", keyword)
            
        return jobs


# 싱글톤 인스턴스
saramin_tool = SaraminTool()
