"""[Infrastructure Tool Layer] 고용24(워크넷) Open API XML/JSON 연동 도구."""
import xml.etree.ElementTree as ET
from typing import Any, Callable

import requests

from core.config import settings
from tools.base_tool import BaseTool


class WorknetTool(BaseTool):
    """
    고용24(work24.go.kr) Open API를 캡슐화한다.
    채용행사/공채속보/공채기업정보/직업정보/직무정보 등을 XML·JSON으로 가공.
    """

    name = "worknet_tool"

    WANTED_TYPES = {"채용정보", "채용행사", "공채속보", "공채기업정보"}
    SUPPORTED = WANTED_TYPES | {"직업정보", "직무정보", "강소기업", "학과정보", "훈련과정", "K-Digital_Training"}

    def __init__(self) -> None:
        self._base = settings.WORK24_API_BASE
        self._key_wanted = settings.WORKNET_API_KEY_WANTED
        self._key_job = settings.WORKNET_API_KEY_JOB
        self._key_duty = settings.WORKNET_API_KEY_DUTY
        self._key_map = {
            "강소기업": settings.WORKNET_API_KEY_GANGSO,
            "학과정보": settings.WORKNET_API_KEY_MAJOR,
            "훈련과정": settings.WORKNET_API_KEY_TRAINING_BIZ,
            "K-Digital_Training": getattr(settings, "WORKNET_API_KEY_KDT", None),
        }

    # ===== 캡슐화된 원천 호출 =====
    def _request(self, endpoint_suffix: str, auth_key: str | None, params: dict):
        """(root_element, error_message) 반환."""
        if not auth_key:
            return None, "API 키가 설정되지 않았습니다."
        req_params = {**params, "authKey": auth_key}
        try:
            response = requests.get(f"{self._base}{endpoint_suffix}.do", params=req_params, timeout=12)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            error_el = root.find(".//error")
            if error_el is not None and error_el.text:
                return None, error_el.text.strip()
            return root, None
        except ET.ParseError:
            return None, "API 응답 XML 파싱 실패"
        except Exception as e:  # noqa: BLE001
            return None, str(e)

    # ===== 포매터 =====
    @staticmethod
    def _format_emp_event(item: ET.Element, idx: int) -> str:
        return (
            f"[{idx}] [고용24/채용행사] {item.findtext('eventNm', '제목 없음')}\n"
            f"지역: {item.findtext('area', '')} | 기간: {item.findtext('eventTerm', '')}\n"
            f"행사번호: {item.findtext('eventNo', '')}\n"
        )

    @staticmethod
    def _format_gongchae_sokbo(item: ET.Element, idx: int) -> str:
        url = item.findtext("empWantedHomepgDetail", "")
        return (
            f"[{idx}] [고용24/공채속보] {item.findtext('empWantedTitle', '제목 없음')}\n"
            f"기업: {item.findtext('empBusiNm', '')} ({item.findtext('coClcdNm', '')})\n"
            f"모집기간: {item.findtext('empWantedStdt', '')} ~ {item.findtext('empWantedEndt', '')}\n"
            f"채용형태: {item.findtext('empWantedTypeNm', '')}\n"
            f"URL: {url}\n"
        )

    @staticmethod
    def _format_gongchae_company(item: ET.Element, idx: int) -> str:
        return (
            f"[{idx}] [고용24/공채기업정보] {item.findtext('coNm', '기업명 없음')}\n"
            f"유형: {item.findtext('coClcdNm', '')}\n"
            f"소개: {item.findtext('coIntroSummaryCont', '')}\n"
            f"홈페이지: {item.findtext('homepg', '')}\n"
        )

    # ===== 검색 메서드 =====
    def _search_wanted_bundle(self, keyword: str, only: str | None = None) -> str:
        base_params = {"callTp": "L", "returnType": "XML", "startPage": "1", "display": "10", "keyword": keyword}
        sources: list[tuple[str, str, str, Callable]] = [
            ("채용행사", "210L11", ".//empEvent", self._format_emp_event),
            ("공채속보", "210L21", ".//dhsOpenEmpInfo", self._format_gongchae_sokbo),
            ("공채기업정보", "210L31", ".//dhsOpenEmpHireInfo", self._format_gongchae_company),
        ]
        if only:
            sources = [s for s in sources if s[0] == only]

        sections: list[str] = []
        for label, endpoint, xpath, formatter in sources:
            root, err = self._request(endpoint, self._key_wanted, base_params)
            if err:
                sections.append(f"## {label}\n(조회 불가: {err})")
                continue
            items = root.findall(xpath)
            if not items:
                sections.append(f"## {label}\n'{keyword}' 관련 결과 없음")
                continue

            # Guardrail: 필터링을 통해 검색 키워드와 무관한 결과(오탐) 제거
            query_tokens = [t.lower() for t in keyword.split() if len(t) >= 2]
            filtered_items = []
            for item in items:
                item_text = "".join(c.text.lower() for c in item if c.text)
                # 키워드가 2글자 이상인 토큰이 없으면 그냥 통과, 있으면 최소 1개 이상 포함되어야 함
                if not query_tokens or any(tok in item_text for tok in query_tokens):
                    filtered_items.append(item)

            if not filtered_items:
                sections.append(f"## {label}\n'{keyword}' 관련 결과 없음 (필터링됨)")
                continue

            lines = [formatter(item, i) for i, item in enumerate(filtered_items[:10], 1)]
            sections.append(f"## {label} ({len(filtered_items)}건)\n" + "\n".join(lines))

        combined = "\n\n".join(sections)
        if all("결과 없음" in s or "조회 불가" in s for s in sections):
            return f"워크넷(고용24)에서 '{keyword}' 관련 채용정보를 찾을 수 없습니다.\n\n{combined}"
        return combined

    def _search_job_info(self, keyword: str) -> str:
        root, err = self._request("212L01", self._key_job, {
            "returnType": "XML", "target": "JOBCD", "srchType": "K", "keyword": keyword,
        })
        if err:
            return f"워크넷 직업정보 API 오류: {err}"
        items = root.findall(".//jobList")
        if not items:
            return f"워크넷에서 '{keyword}' 관련 직업정보를 찾을 수 없습니다."
        lines = []
        for idx, item in enumerate(items[:10], 1):
            lines.append(
                f"[{idx}] [고용24/직업정보] {item.findtext('jobNm', '직업명 없음')}\n"
                f"분류: {item.findtext('jobClcdNM', '')}\n"
                + "".join(f"- {c.tag}: {(c.text or '')[:150]}\n" for c in item if c.text and c.text.strip())
            )
        return "\n".join(lines)

    def _search_duty_info(self, keyword: str) -> str:
        if not self._key_duty:
            return "워크넷 직무정보 API 키가 설정되지 않았습니다."
        try:
            response = requests.get(
                f"{self._base}215L11.do",
                params={"authKey": self._key_duty, "word": keyword, "limit": "10", "returnType": "JSON"},
                timeout=12,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:  # noqa: BLE001
            return f"워크넷 직무정보 API 오류: {e}"

        if data.get("error"):
            return f"워크넷 직무정보 API 오류: {data['error']}"
        result = data.get("result", {})
        if not result:
            return f"워크넷에서 '{keyword}' 관련 직무정보(NCS)를 찾을 수 없습니다."

        lines = []
        for idx, (name, info) in enumerate(list(result.items())[:10], 1):
            if isinstance(info, dict):
                lines.append(
                    f"[{idx}] [고용24/직무정보] {name}\n"
                    f"정의: {info.get('ablt_def', '')}\n"
                    f"대분류: {info.get('job_lcfn', '')} > {info.get('job_mcn', '')} > {info.get('job_scfn', '')}\n"
                )
            else:
                lines.append(f"[{idx}] [고용24/직무정보] {name}: {info}\n")
        return "\n".join(lines)

    def _search_k_digital_training(self, keyword: str) -> str:
        key = self._key_map.get("K-Digital_Training")
        if not key:
            return "HRD-Net K-Digital Training API 키가 설정되지 않았습니다."
        # HRD-Net 훈련과정 API
        try:
            url = "https://www.hrd.go.kr/jsp/HRDP/HRDPWZ/HRDPWZ60/HRDPWZ60_1.jsp"
            params = {
                "authKey": key,
                "returnType": "XML",
                "outType": "1",
                "pageNum": "1",
                "pageSize": "10",
                "srchTraProcessNm": keyword,
                "sort": "ASC",
                "sortCol": "TRNG_BGDE",
            }
            res = requests.get(url, params=params, timeout=12)
            res.raise_for_status()
            root = ET.fromstring(res.content)
        except Exception as e:
            return f"K-Digital Training 검색 실패: {e}"

        items = root.findall(".//scn_list")
        if not items:
            return f"'{keyword}' 관련 K-Digital Training(부트캠프) 과정을 찾을 수 없습니다."

        lines = []
        for idx, item in enumerate(items[:10], 1):
            title = item.findtext("title", "과정명 없음")
            inst = item.findtext("subTitle", "기관명 없음")
            period = f"{item.findtext('traStartDate', '')} ~ {item.findtext('traEndDate', '')}"
            link = item.findtext("titleLink", "")
            lines.append(
                f"[{idx}] [HRD-Net/K-Digital_Training] {title}\n"
                f"훈련기관: {inst}\n"
                f"훈련기간: {period}\n"
                f"URL: {link}\n"
            )
        return "\n".join(lines)

    # ===== 공개 인터페이스 =====
    def execute(self, query: str, **kwargs: Any) -> str:
        """search_type별 통합 검색 진입점."""
        search_type = kwargs.get("search_type", "채용정보")
        keyword = query.strip()

        if search_type not in self.SUPPORTED:
            return f"현재 '{search_type}' 검색은 지원하지 않습니다. (가능: {', '.join(sorted(self.SUPPORTED))})"

        from services.vector_cache_service import vector_cache_service
        cache_key = f"worknet_{search_type}_{keyword}"

        # 1. 벡터 DB 캐시 조회
        cached = vector_cache_service.query_context(cache_key, threshold=1.0)
        if cached:
            return cached[0]

        # 2. 캐시 미스 시 실시간 검색 및 가공
        if search_type in self.WANTED_TYPES:
            only = None if search_type == "채용정보" else search_type
            result_str = self._search_wanted_bundle(keyword, only)
        elif search_type == "직업정보":
            result_str = self._search_job_info(keyword)
        elif search_type == "직무정보":
            result_str = self._search_duty_info(keyword)
        elif search_type == "K-Digital_Training":
            result_str = self._search_k_digital_training(keyword)
        else:
            if not self._key_map.get(search_type):
                return f"워크넷 {search_type} API 키가 설정되지 않았습니다."
            result_str = (
                f"워크넷 '{search_type}' API는 고용24(work24.go.kr)에서 별도 Open API 신청·승인이 필요합니다. "
                f"현재 연동 가능: 채용행사, 공채속보, 공채기업정보, 직업정보, 직무정보. "
                f"대신 search_type='채용정보' 또는 '공채속보'로 '{keyword}' 키워드를 검색해 보세요."
            )

        # 3. 벡터 DB에 결과 캐싱 (에러 메시지가 아닌 경우에만)
        if result_str and "오류" not in result_str and "조회 불가" not in result_str:
            vector_cache_service.cache_context(cache_key, result_str, [])

        return result_str

    # ===== 자동완성용 용어 조회 (term, source) 튜플 리스트 =====
    def fetch_job_names(self, q: str, limit: int = 8) -> list[tuple[str, str]]:
        if not self._key_job or not q:
            return []
        root, err = self._request("212L01", self._key_job, {
            "returnType": "XML", "target": "JOBCD", "srchType": "K", "keyword": q,
        })
        if err or root is None:
            return []
        out: list[tuple[str, str]] = []
        for item in root.findall(".//jobList")[:limit]:
            name = (item.findtext("jobNm", "") or "").strip()
            if name:
                out.append((name, "고용24·직업"))
        return out

    def fetch_duty_names(self, q: str, limit: int = 8) -> list[tuple[str, str]]:
        if not self._key_duty or not q:
            return []
        try:
            response = requests.get(
                f"{self._base}215L11.do",
                params={"authKey": self._key_duty, "word": q, "limit": str(limit), "returnType": "JSON"},
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:  # noqa: BLE001
            return []
        if data.get("error"):
            return []
        result = data.get("result") or {}
        if not isinstance(result, dict):
            return []
        return [(name.strip(), "고용24·직무") for name in list(result.keys())[:limit] if name.strip()]

    def fetch_company_names(self, q: str, limit: int = 8) -> list[tuple[str, str]]:
        if not self._key_wanted or not q:
            return []
        root, err = self._request("210L31", self._key_wanted, {
            "callTp": "L", "returnType": "XML", "startPage": "1", "display": str(limit), "keyword": q,
        })
        if err or root is None:
            return []
        out: list[tuple[str, str]] = []
        for item in root.findall(".//dhsOpenEmpHireInfo")[:limit]:
            name = (item.findtext("coNm", "") or "").strip()
            if name:
                out.append((name, "고용24·기업"))
        return out

    def fetch_sokbo_terms(self, q: str, limit: int = 8) -> list[tuple[str, str]]:
        if not self._key_wanted or not q:
            return []
        root, err = self._request("210L21", self._key_wanted, {
            "callTp": "L", "returnType": "XML", "startPage": "1", "display": str(limit), "keyword": q,
        })
        if err or root is None:
            return []
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in root.findall(".//dhsOpenEmpInfo")[:limit]:
            for tag, source in (("empBusiNm", "공채속보·기업"), ("empWantedTitle", "공채속보")):
                val = (item.findtext(tag, "") or "").strip()
                if val and val not in seen and len(val) <= 60:
                    seen.add(val)
                    out.append((val, source))
        return out


# 싱글톤 인스턴스
worknet_tool = WorknetTool()
