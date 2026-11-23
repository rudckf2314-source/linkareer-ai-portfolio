"""[Infrastructure Tool Layer] Tavily Client 캡슐화 및 링커리어 마이닝 도구."""
import logging
from datetime import date
from typing import Any

import requests
from tavily import TavilyClient

from core.activity_filter import filter_activity_dicts, is_recruiting_activity
from core.config import settings
from tools.base_tool import BaseTool

logger = logging.getLogger(__name__)


class TavilyTool(BaseTool):
    """Tavily 검색 API를 캡슐화한다. 링커리어 사이트 마이닝에 특화."""

    name = "tavily_tool"

    def __init__(self) -> None:
        self._api_key = settings.TAVILY_API_KEY

    # ----- 내부 캡슐화된 원천 호출 -----
    def _client(self) -> TavilyClient:
        return TavilyClient(api_key=self._api_key)

    def _raw_search(self, query: str, depth: str = "basic", max_results: int = 10) -> list[dict]:
        if not self._api_key:
            return []
        try:
            resp = self._client().search(query=query, search_depth=depth, max_results=max_results)
            return resp.get("results", [])
        except Exception as exc:
            logger.warning("Tavily search failed for %r: %s", query[:80], exc)
            return []

    def _serper_search(self, query: str, *, max_results: int = 20) -> list[dict]:
        """Serper(Google) 검색 — Tavily 한도 초과 시 기업분석 등 폴백."""
        serper_key = settings.SERPER_API_KEY
        if not serper_key:
            return []
        try:
            response = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": query, "num": max_results, "gl": "kr", "hl": "ko"},
                timeout=15,
            )
            if not response.ok:
                logger.warning("Serper search HTTP %s for %r", response.status_code, query[:80])
                return []
            return [
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "content": item.get("snippet", ""),
                }
                for item in response.json().get("organic", [])
            ]
        except Exception as exc:
            logger.warning("Serper search failed for %r: %s", query[:80], exc)
            return []

    # ----- 공개 인터페이스 -----
    def execute(self, query: str, **kwargs: Any) -> list[dict]:
        """일반 Tavily 검색. results 리스트를 그대로 반환."""
        depth = kwargs.get("depth", "basic")
        max_results = kwargs.get("max_results", 10)
        return self._raw_search(query, depth=depth, max_results=max_results)

    def search_linkareer_active(self, keyword: str, limit: int = 8) -> list[dict]:
        """
        링커리어 활동 중 '마감 전(D-)' 항목만 반환 (하네스 로드맵 추천 전용).
        마감(D+)·과거 연도·종료된 공모전은 제외한다.
        """
        from services.vector_cache_service import vector_cache_service
        
        # 1. 벡터 DB 캐시 조회
        cached = vector_cache_service.query_activities(keyword, limit=limit, threshold=1.0)
        # 링커리어 활동 필터링
        linkareer_cached = [c for c in cached if c.get("source_platform") == "링커리어(Tavily)"]
        if len(linkareer_cached) >= 3:
            # 캐시 포맷 맞추기: {"title": "...", "link": "...", "snippet": "..."}
            return [{"title": c["title"], "link": c["link_url"], "snippet": c["snippet"]} for c in linkareer_cached]

        # 2. 캐시가 부족한 경우 실시간 검색 수행
        year = date.today().year
        items: list[dict] = []
        for item in self._raw_search(
            f"site:linkareer.com/activity {keyword} (모집중 OR 상시모집) {year}",
            max_results=20,
        ):
            url = item.get("url", "")
            if "linkareer.com" not in url:
                continue
            title = (item.get("title") or "").split(" | ")[0].strip()
            snippet = (item.get("content") or "")[:300]
            blob = title + " " + snippet
            if "D+" in blob:
                continue
            if not is_recruiting_activity(title, snippet, require_active_signal=True):
                continue
            items.append({"title": title, "link": url, "snippet": snippet})
            if len(items) >= limit:
                break
        
        results = filter_activity_dicts(items, require_active_signal=True)
        
        # 3. 신규 수집 결과 벡터 DB에 캐싱
        if results:
            vector_cache_service.cache_activities(results, "링커리어(Tavily)", keyword)
            
        return results

    def search_saramin_fallback(self, keyword: str) -> list[dict]:
        """사람인 폴백 검색용 결과 (Serper 실패 시 SaraminTool이 호출)."""
        jobs: list[dict] = []
        kw = keyword.strip()
        for q in (f"site:saramin.co.kr {kw} 채용공고", f"saramin.co.kr {kw} 채용공고"):
            for item in self._raw_search(q, max_results=20):
                link = item.get("url", "")
                if "saramin.co.kr" not in link:
                    continue
                jobs.append({
                    "title": item.get("title", "").strip(),
                    "link": link,
                    "snippet": item.get("content", "").strip(),
                })
            if jobs:
                break
        return jobs

    def mine_context(self, query: str, max_results: int = 8) -> tuple[str, list[dict]]:
        """
        에이전트 추론용 컨텍스트 마이닝.
        (LLM 컨텍스트 텍스트, 링커리어 출처 ref 리스트) 반환.
        """
        from services.vector_cache_service import vector_cache_service
        
        # 1. 벡터 DB 캐시 조회
        cached = vector_cache_service.query_context(query, threshold=1.0)
        if cached:
            return cached

        # 2. 캐시 미스 시 실시간 수집
        ctx_lines, refs = [], []
        for item in self._raw_search(query, depth="advanced", max_results=max_results):
            title = (item.get("title") or "").split(" | ")[0].strip()
            url = item.get("url", "")
            content = (item.get("content") or "")[:400]
            ctx_lines.append(f"- {title}: {content} (URL: {url})")
            if "linkareer.com" in url:
                refs.append({"label": "링커리어 실시간 소싱 데이터", "title": title, "url": url})
        
        context_text = "\n".join(ctx_lines)
        
        # 3. 벡터 DB에 결과 캐싱
        if context_text:
            vector_cache_service.cache_context(query, context_text, refs)
            
        return context_text, refs

    def search_linkareer_agent(self, query: str) -> str:
        """
        링커리어 전용 검색 + 카테고리 필터링 (채팅 에이전트 도구용).
        기존 search_linkareer @tool 의 가공 로직을 캡슐화.
        """
        if any(k in query for k in ["공모전", "대외활동", "서포터즈", "동아리", "모집"]):
            refined = f"site:linkareer.com/activity {query}"
        elif "기업분석" in query:
            refined = f"site:linkareer.com/company-analysis {query}"
        elif "기업정보" in query:
            refined = f"site:linkareer.com/company-info {query}"
        else:
            refined = f"site:linkareer.com {query}"

        try:
            resp = self._client().search(
                query=refined, search_depth="advanced", max_results=30, include_answer=True,
            )
        except Exception as e:
            return f"검색 중 오류가 발생했습니다: {str(e)}"

        results = resp.get("results", [])
        if not results:
            return "링커리어 검색 결과가 없습니다."

        formatted = []
        for idx, item in enumerate(results, 1):
            title = item.get("title", "")
            content = item.get("content", "")
            clean_title = title.split(" | ")[0]
            if "D+" in content:
                continue
            if "공모전" in query:
                if not any(k in clean_title for k in ["공모전", "챌린지", "대회"]):
                    continue
            elif "대외활동" in query:
                if not any(k in clean_title for k in ["대외활동", "기자단", "홍보대사", "동아리", "아카데미", "교육", "서포터즈", "부트캠프", "기"]):
                    continue
            elif "모집 공고" in query or "인턴" in query or "채용" in query:
                if "채용형태" not in content and not any(k in clean_title for k in ["인턴", "채용"]):
                    continue
            formatted.append(
                f"[{idx}] 제목: {title}\nURL: {item.get('url')}\n내용 요약: {content}\n"
            )

        if not formatted:
            return "요청하신 조건(키워드 및 마감 기한)에 완벽하게 부합하는 링커리어 활동이 없습니다."
        return "\n".join(formatted[:10])

    def search_linkareer_company_analysis(self, query: str, *, max_results: int = 25) -> list[dict]:
        """링커리어 기업분석자료 전용 검색 (company-analysis URL만). Tavily 실패 시 Serper 폴백."""
        from core.company_analysis_matcher import normalize_viewer_url

        def _collect(raw_items: list[dict]) -> list[dict]:
            items: list[dict] = []
            for item in raw_items or []:
                url = item.get("url", "")
                clean_url = normalize_viewer_url(url)
                if not clean_url:
                    continue
                title = (item.get("title") or "").split(" | ")[0].strip()
                if not title:
                    continue
                items.append({
                    "title": title,
                    "url": clean_url,
                    "link": clean_url,
                    "snippet": (item.get("content") or item.get("snippet") or "")[:400],
                    "content": item.get("content") or item.get("snippet") or "",
                })
            return items

        items = _collect(self._raw_search(query, depth="advanced", max_results=max_results))
        if items:
            return items

        serper_items = _collect(self._serper_search(query, max_results=max_results))
        if serper_items:
            logger.info("[TavilyTool] company-analysis Serper fallback: %d hits for %r", len(serper_items), query[:60])
        return serper_items


# 싱글톤 인스턴스
tavily_tool = TavilyTool()
