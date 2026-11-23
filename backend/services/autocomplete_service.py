"""[Business Service Layer] 고용24 용어 병렬 조회 자동완성 서비스."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from tools.worknet_tool import worknet_tool

KEYWORD_PRESETS = [
    "백엔드 개발자", "프론트엔드 개발자", "풀스택 개발자", "데이터 분석가",
    "AI/ML 엔지니어", "DevOps", "클라우드 엔지니어", "정보보안", "QA 엔지니어",
    "PM", "서비스 기획", "마케팅", "UX/UI 디자이너", "청소년 상담", "학교 상담",
    "IT/플랫폼", "게임", "커머스",
]
# 자동완성 빈 입력 시에만 표시 (기업 탐색 결과와 무관)
COMPANY_PRESETS: list[str] = []


class AutocompleteService:
    """
    고용24(워크넷) 용어를 ThreadPoolExecutor로 병렬 조회하는 자동완성 서비스.
    executor는 멤버로 관리하며 객체 소멸 시 안전하게 shutdown 한다.
    """

    def __init__(self, max_workers: int = 5) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._worknet = worknet_tool

    def __del__(self) -> None:
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass

    def _fetchers_for(self, context: str):
        if context == "company":
            return [self._worknet.fetch_company_names, self._worknet.fetch_sokbo_terms]
        if context == "field":
            return [self._worknet.fetch_job_names, self._worknet.fetch_duty_names]
        # job (기본)
        return [self._worknet.fetch_job_names, self._worknet.fetch_duty_names, self._worknet.fetch_sokbo_terms]

    def suggest(self, query: str, context: str = "job", limit: int = 12) -> list[dict]:
        q = query.strip()
        seen: set[str] = set()
        results: list[dict] = []

        def add(text: str, source: str) -> None:
            text = text.strip()
            if text and text not in seen:
                seen.add(text)
                results.append({"text": text, "source": source})

        presets = COMPANY_PRESETS if context == "company" else KEYWORD_PRESETS

        if not q:
            for p in presets[:limit]:
                add(p, "인기")
            return results

        if len(q) == 1:
            for p in presets:
                if q.lower() in p.lower():
                    add(p, "인기")
            return results[:limit]

        # 2글자 이상 → 고용24 API 병렬 조회
        fetchers = self._fetchers_for(context)
        # fetchers 리스트 순서가 우선순위이므로 순서대로 수집합니다.
        futures = [self._executor.submit(fn, q, 8) for fn in fetchers]
        for fut in futures:
            try:
                for text, source in fut.result(timeout=2.0):
                    add(text, source)
                    if len(results) >= limit:
                        return results[:limit]
            except Exception:
                continue

        for p in presets:
            if q in p and len(results) < limit:
                add(p, "인기")
        return results[:limit]


# 싱글톤 인스턴스
autocomplete_service = AutocompleteService()
