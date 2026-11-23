"""
[Rule-based Cover Letter Registry] 합격 자소서 수집 고정 규칙 (SSOT).

벤치마킹(4단계) / Cover_Letter_Search_Tool 이 참조하는 Base URL·파싱 경로.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from core.crawler_rules import DEFAULT_HEADERS, JSON_HEADERS

CoverLetterKind = Literal["cover_letter"]

ALLOWED_DOMAINS = (
    "linkareer.com",
    "jobkorea.co.kr",
    "saramin.co.kr",
    "wanted.co.kr",
)

MIN_COVER_LETTER_COUNT = 3
MAX_DETAIL_SCRAPE = 12

# 직무 → 링커리어 roleIds 기본값 (동적 매칭 실패 시 폴백)
DEFAULT_ROLE_ID = "server-backend-developer"

# @deprecated — peer_companies / JOB_ROLE_IDS 제거됨.
# 매칭은 services/recommendation_engine.py 임베딩 스코어 사용.


@dataclass(frozen=True)
class CoverLetterParseRule:
    method: Literal["next_apollo", "html", "json_api", "playwright"]
    list_selector: str = ""
    link_pattern: str = ""
    link_prefix: str = ""
    apollo_typename: str = "CoverLetter"
    apollo_id_field: str = "id"
    apollo_company_field: str = "organizationName"
    apollo_title_field: str = "title"
    detail_url_template: str = ""
    api_url: str = ""
    api_jobs_path: tuple[str, ...] = ("data",)


@dataclass(frozen=True)
class CoverLetterTarget:
    site_id: str
    site_name: str
    home_url: str
    navigation_path: str
    list_url: str
    source_platform: str
    parse: CoverLetterParseRule
    query_params: dict[str, str] = field(default_factory=dict)
    request_delay_sec: tuple[float, float] = (1.0, 2.0)
    notes: str = ""


LINKAREER_COVER_LETTER = CoverLetterTarget(
    site_id="linkareer_cover_letter",
    site_name="링커리어",
    home_url="https://linkareer.com/",
    navigation_path="메인 → [자소서 만능 검색기] → IT/인터넷 → 서버/백엔드 개발자",
    list_url="https://linkareer.com/cover-letter/search",
    source_platform="링커리어",
    query_params={"roleIds": DEFAULT_ROLE_ID},
    parse=CoverLetterParseRule(
        method="next_apollo",
        apollo_typename="CoverLetter",
        apollo_id_field="id",
        apollo_company_field="organizationName",
        detail_url_template="https://linkareer.com/cover-letter/{id}",
    ),
    notes="비로그인 HTML/Apollo 파싱. 리스트 → /cover-letter/{id} 상세 루프.",
)

SARAMIN_COVER_LETTER = CoverLetterTarget(
    site_id="saramin_cover_letter",
    site_name="사람인",
    home_url="https://www.saramin.co.kr/",
    navigation_path="메인 → [커리어레시피] → [합격자소서] → 서버/백엔드개발 (10217)",
    list_url="https://www.saramin.co.kr/zf_user/company-review-cover-letter/list",
    source_platform="사람인",
    query_params={"job_category_cd": "10217"},
    parse=CoverLetterParseRule(
        method="playwright",
        list_selector='a[href*="rec_idx"], a[href*="cover"]',
        link_prefix="https://www.saramin.co.kr",
        detail_url_template="https://www.saramin.co.kr{path}",
    ),
    request_delay_sec=(1.5, 3.0),
    notes="Anti-Bot 강함 — Playwright + fake-useragent + 1.5~3초 딜레이.",
)

WANTED_COVER_LETTER = CoverLetterTarget(
    site_id="wanted_cover_letter",
    site_name="원티드",
    home_url="https://www.wanted.co.kr/",
    navigation_path="메인 → [커리어 조회] → [합격 이력서] → 개발/백엔드/신입·인턴",
    list_url="https://www.wanted.co.kr/wdlist/518/872",
    source_platform="원티드",
    query_params={"years": "0"},
    parse=CoverLetterParseRule(
        method="json_api",
        api_url="https://www.wanted.co.kr/api/v4/resumes/matched",
        detail_url_template="https://www.wanted.co.kr/api/v4/resumes/{id}",
    ),
    notes="JWT 필수 (GOOGLE_REFRESH_TOKEN 아님 — .env WANTED_JWT_TOKEN). DOM 크롤링 금지.",
)

COVER_LETTER_TARGETS: tuple[CoverLetterTarget, ...] = (
    LINKAREER_COVER_LETTER,
    SARAMIN_COVER_LETTER,
    WANTED_COVER_LETTER,
)

FALLBACK_MESSAGES = {
    2: (
        "타겟 기업의 합격 자소서가 부족하여, 동일 [{field}] 분야 대기업군의 "
        "[{job}] 합격 자소서를 종합 분석하였습니다."
    ),
    3: (
        "타겟 기업·동급 기업군 데이터가 부족하여, 동일 분야 전체 "
        "[{job}] 합격 자소서 풀을 기반으로 직무 중심 벤치마킹을 수행하였습니다."
    ),
}


def resolve_role_id(job: str) -> str:
    """메타 테이블 임베딩 매칭 — 정적 if-else 없음."""
    try:
        from services.recommendation_engine import recommendation_engine
        return recommendation_engine.resolve_linkareer_role_slug(job)
    except Exception:
        return DEFAULT_ROLE_ID


def resolve_field_key(field: str) -> str:
    """표시용 분야 라벨 (하드 매핑 최소화)."""
    return (field or "IT").strip()[:32] or "IT"


def peer_companies(field: str, exclude: str = "") -> tuple[str, ...]:
    """@deprecated — recommendation_engine 사용. 하위 호환용 빈 튜플."""
    return ()


def build_cover_letter_list_url(
    target: CoverLetterTarget,
    *,
    company: str = "",
    role_id: str = "",
) -> str:
    from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

    parsed = urlparse(target.list_url)
    params = dict(target.query_params)
    if target.site_id == "linkareer_cover_letter":
        params["roleIds"] = role_id or DEFAULT_ROLE_ID
        if company.strip():
            params["keyword"] = company.strip()
    elif target.site_id == "saramin_cover_letter" and company.strip():
        params["searchword"] = company.strip()

    existing = parse_qs(parsed.query)
    for k, v in params.items():
        existing[k] = [v]
    flat = {k: v[0] for k, v in existing.items()}
    return urlunparse(parsed._replace(query=urlencode(flat)))
