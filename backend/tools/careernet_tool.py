"""[Infrastructure Tool Layer] 커리어넷(career.go.kr) Open API — 보조 진로 데이터."""
from typing import Any

import requests

from core.config import settings
from tools.base_tool import BaseTool


class CareerNetTool(BaseTool):
    """
    커리어넷 공공 진로 API 캡슐화.
    채용/공고의 1차 소스가 아니라 전공-직무 연계·진로 맥락 보조용으로만 사용한다.
    """

    name = "careernet_tool"
    SUPPORTED = {"직업정보", "학과정보"}

    def __init__(self) -> None:
        self._key = settings.CAREERNET_API_KEY
        self._openapi = settings.CAREERNET_OPENAPI_BASE
        self._junior = settings.CAREERNET_JUNIOR_BASE

    def _get_json(self, url: str, params: dict) -> dict | None:
        if not self._key:
            return None
        try:
            resp = requests.get(url, params={**params, "apiKey": self._key}, timeout=12)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def _search_major(self, keyword: str) -> str:
        data = self._get_json(
            self._openapi,
            {
                "svcType": "api",
                "svcCode": "MAJOR",
                "contentType": "json",
                "gubun": "대학교",
                "searchTitle": keyword,
                "thisPage": "1",
                "perPage": "8",
            },
        )
        if not data:
            return "커리어넷 학과정보 API를 호출할 수 없습니다."
        items = (data.get("dataSearch") or {}).get("content") or []
        if not items:
            return (
                f"커리어넷에서 '{keyword}' 관련 학과정보를 찾지 못했습니다. "
                "(API 키 권한 또는 검색어를 확인하세요.)"
            )
        lines = []
        for idx, item in enumerate(items[:8], 1):
            if not isinstance(item, dict):
                continue
            name = item.get("majorNm") or item.get("mClass") or item.get("title") or "학과명 없음"
            summary = (item.get("summary") or item.get("majorSummary") or item.get("intro") or "")[:200]
            lines.append(f"[{idx}] [커리어넷/학과] {name}\n{summary}\n")
        return "\n".join(lines) if lines else f"커리어넷에서 '{keyword}' 학과정보 결과를 파싱하지 못했습니다."

    def _search_jobs(self, keyword: str) -> str:
        data = self._get_json(
            f"{self._junior}/juniorjobsinfo.json",
            {"searchJobNm": keyword, "pageIndex": "1"},
        )
        if not data:
            return "커리어넷 직업정보 API를 호출할 수 없습니다."
        jobs = data.get("jobs") or []
        if not jobs:
            return f"커리어넷에서 '{keyword}' 관련 직업정보를 찾지 못했습니다."

        lines = []
        for idx, job in enumerate(jobs[:5], 1):
            seq = job.get("junior_seq")
            name = job.get("job_nm", "직업명 없음")
            summary = (job.get("job_summary") or "")[:180]
            block = f"[{idx}] [커리어넷/직업] {name}\n요약: {summary}\n"
            if seq:
                detail = self._get_json(f"{self._junior}/juniorjobinfo.json", {"juniorSeq": str(seq)})
                if detail:
                    what = detail.get("what_list") or []
                    how = detail.get("howto_list") or []
                    if what:
                        block += f"하는 일: {what[0][:120]}\n"
                    if how:
                        block += f"준비 방법: {how[0][:120]}\n"
            lines.append(block)
        return "\n".join(lines)

    def execute(self, query: str, **kwargs: Any) -> str:
        keyword = query.strip()
        if not keyword:
            return "검색 키워드를 입력해 주세요."
        if not self._key:
            return "CAREERNET_API_KEY가 설정되지 않았습니다."

        search_type = kwargs.get("search_type", "직업정보")
        if search_type not in self.SUPPORTED:
            return f"커리어넷은 '{search_type}'을 지원하지 않습니다. (가능: {', '.join(sorted(self.SUPPORTED))})"

        from services.vector_cache_service import universal_cache
        cache_key = f"careernet::{search_type}::{keyword}"
        cached = universal_cache.get("careernet", cache_key)
        if cached:
            return cached["text"]

        result = self._search_major(keyword) if search_type == "학과정보" else self._search_jobs(keyword)
        # API 호출 실패 메시지는 캐싱하지 않음 (다음 호출 재시도 허용)
        if result and "API를 호출할 수 없습니다" not in result:
            universal_cache.cache("careernet", cache_key, result)
        return result


careernet_tool = CareerNetTool()
