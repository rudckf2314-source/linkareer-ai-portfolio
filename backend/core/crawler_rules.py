"""
[Rule-based Crawler Registry] 공모전·인턴 공고 수집 고정 규칙.

안티그래비티 개발팀 전달용 Base URL / 파싱 경로 단일 진실 공급원(SSOT).
크롤러 코드는 이 파일의 규칙만 참조하며, URL·셀렉터를 임의 변경하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ActivityKind = Literal["contest", "internship"]


@dataclass(frozen=True)
class ParseRule:
    """HTML/JSON 파싱 경로 — 셀렉터·키 경로를 고정."""

    method: Literal["html", "next_apollo", "json_api"]
    # HTML
    list_selector: str = ""
    title_selector: str = ""
    link_attr: str = "href"
    link_prefix: str = ""
    snippet_selector: str = ""
    # Next.js Apollo (__NEXT_DATA__)
    next_data_script_id: str = "__NEXT_DATA__"
    apollo_state_path: tuple[str, ...] = ("props", "pageProps", "__APOLLO_STATE__")
    apollo_typename: str = "Activity"
    apollo_title_field: str = "title"
    apollo_id_field: str = "id"
    detail_url_template: str = ""
    # JSON API
    api_response_jobs_path: tuple[str, ...] = ("data",)
    api_title_fields: tuple[str, ...] = ("position", "title", "name")
    api_id_field: str = "id"
    api_detail_url_template: str = ""


@dataclass(frozen=True)
class CrawlerTarget:
    """사이트별 크롤링 타겟 — 이동 경로·엔드포인트·파싱 규칙."""

    site_id: str
    site_name: str
    kind: ActivityKind
    home_url: str
    navigation_path: str
    list_url: str
    source_platform: str
    parse: ParseRule
    request_delay_sec: tuple[float, float] = (1.0, 2.0)
    notes: str = ""
    query_params: dict[str, str] = field(default_factory=dict)


# ── 공통 HTTP 헤더 (사람인·원티드 봇 차단 대응) ─────────────────────────
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

JSON_HEADERS: dict[str, str] = {
    **DEFAULT_HEADERS,
    "Accept": "application/json",
}


# ═══════════════════════════════════════════════════════════════════════
# 1. 공모전 (Contest) — Phase 3
# ═══════════════════════════════════════════════════════════════════════

LINKAREER_CONTEST = CrawlerTarget(
    site_id="linkareer_contest",
    site_name="링커리어",
    kind="contest",
    home_url="https://linkareer.com/",
    navigation_path="메인 → [공모전] → IT/SW/게임/웹/앱 필터",
    list_url="https://linkareer.com/list/contest",
    source_platform="링커리어",
    query_params={"filter_ids": "it-sw-game-web-app"},
    parse=ParseRule(
        method="next_apollo",
        next_data_script_id="__NEXT_DATA__",
        apollo_state_path=("props", "pageProps", "__APOLLO_STATE__"),
        apollo_typename="Activity",
        apollo_title_field="title",
        apollo_id_field="id",
        detail_url_template="https://linkareer.com/activity/{id}",
    ),
    notes="Next.js __NEXT_DATA__ → Apollo Activity 노드. filter_ids=it-sw-game-web-app 고정.",
)

WEVITY_CONTEST_IT = CrawlerTarget(
    site_id="wevity_contest_it",
    site_name="위비티",
    kind="contest",
    home_url="https://www.wevity.com/",
    navigation_path="메인 → [공모전] → [웹/모바일/IT/SW] (cat=30)",
    list_url="https://www.wevity.com/",
    source_platform="위비티",
    query_params={"c": "find", "s": "1", "gub": "1", "cat": "30"},
    parse=ParseRule(
        method="html",
        list_selector=".list a",
        title_selector="",
        link_attr="href",
        link_prefix="https://www.wevity.com/",
        detail_url_template="https://www.wevity.com/?c=find&s=1&gub=1&gbn=view&gp=1&ix={id}",
    ),
    notes="cat=30 = IT/SW 고유 코드. .list a 리스트 파싱.",
)


# ═══════════════════════════════════════════════════════════════════════
# 2. 인턴/채용 (Internship) — Phase 4
# ═══════════════════════════════════════════════════════════════════════

SARAMIN_INTERN = CrawlerTarget(
    site_id="saramin_intern",
    site_name="사람인",
    kind="internship",
    home_url="https://www.saramin.co.kr/",
    navigation_path="메인 → [채용정보] → [공채/인턴] → 고용형태 [인턴]",
    list_url="https://www.saramin.co.kr/zf_user/jobs/public/list",
    source_platform="사람인",
    query_params={"employment_type": "intern"},
    parse=ParseRule(
        method="html",
        list_selector='a[href*="rec_idx"]',
        title_selector=".job_tit",
        link_attr="href",
        link_prefix="https://www.saramin.co.kr",
    ),
    request_delay_sec=(1.0, 2.0),
    notes="봇 차단 강함 — User-Agent 필수, 요청 간 1~2초 랜덤 딜레이.",
)

WANTED_INTERN_BACKEND = CrawlerTarget(
    site_id="wanted_intern_backend",
    site_name="원티드",
    kind="internship",
    home_url="https://www.wanted.co.kr/",
    navigation_path="메인 → [채용] → 개발 → 서버/백엔드 → 신입/인턴 필터",
    list_url="https://www.wanted.co.kr/wdlist/518/872",
    source_platform="원티드",
    query_params={"years": "0"},
    parse=ParseRule(
        method="json_api",
        api_response_jobs_path=("data",),
        api_title_fields=("position", "title", "name"),
        api_id_field="id",
        api_detail_url_template="https://www.wanted.co.kr/wd/{id}",
    ),
    notes=(
        "DOM 스크래핑 금지. /api/v4/jobs JSON API 직접 호출. "
        "518=개발, 872=서버/백엔드, years=0=신입/인턴."
    ),
)

# 원티드 JSON API — DOM 스크래핑 대신 직접 호출 (v4 jobs)
WANTED_JOBS_API_URL = (
    "https://www.wanted.co.kr/api/v4/jobs"
    "?country=kr&job_sort=job.latest_order"
    "&years%5B%5D=0&job_category_id=518&job_category_tag_type_id=872"
)

_TECH_FIELD_HINTS = (
    "개발", "it", "sw", "엔지니어", "engineer", "프로그래", "데이터", "ai",
    "백엔드", "프론트", "서버", "웹", "앱", "게임", "소프트", "dev",
)
_WANTED_TAG_BY_ROLE = (
    (("백엔드", "backend", "서버", "be", "api"), 872),
)


def build_wanted_jobs_api_url(
    *,
    field: str = "",
    job: str = "",
    limit: int = 20,
) -> str:
    """분야·직무 기반 원티드 인턴 API URL (query + 직군 태그 동적 조립)."""
    from urllib.parse import urlencode

    blob = f"{field} {job}".lower()
    params: dict[str, str | list[str]] = {
        "country": "kr",
        "job_sort": "job.latest_order",
        "years[]": "0",
        "limit": str(max(8, limit)),
    }
    if any(h in blob for h in _TECH_FIELD_HINTS):
        params["job_category_id"] = "518"
        for hints, tag_id in _WANTED_TAG_BY_ROLE:
            if any(h in blob for h in hints):
                params["job_category_tag_type_id"] = str(tag_id)
                break
    q = " ".join(dict.fromkeys([field.strip(), job.strip()])).strip()
    if q:
        params["query"] = q
    return f"https://www.wanted.co.kr/api/v4/jobs?{urlencode(params, doseq=True)}"

# ── 레지스트리 ─────────────────────────────────────────────────────────

CONTEST_TARGETS: tuple[CrawlerTarget, ...] = (LINKAREER_CONTEST, WEVITY_CONTEST_IT)
INTERNSHIP_TARGETS: tuple[CrawlerTarget, ...] = (SARAMIN_INTERN, WANTED_INTERN_BACKEND)
ALL_TARGETS: tuple[CrawlerTarget, ...] = CONTEST_TARGETS + INTERNSHIP_TARGETS

TARGET_BY_ID: dict[str, CrawlerTarget] = {t.site_id: t for t in ALL_TARGETS}


def build_list_url(target: CrawlerTarget, *, keyword: str = "") -> str:
    """규칙 기반 리스트 URL 조립. keyword는 사람인 searchword 등에만 주입."""
    from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

    parsed = urlparse(target.list_url)
    params = {**target.query_params}
    if keyword.strip() and target.site_id == "saramin_intern":
        params["searchword"] = keyword.strip()
    if target.query_params and not parsed.query:
        query = urlencode(params)
        return urlunparse(parsed._replace(query=query))
    if params:
        existing = parse_qs(parsed.query)
        for k, v in params.items():
            existing[k] = [v]
        flat = {k: v[0] for k, v in existing.items()}
        return urlunparse(parsed._replace(query=urlencode(flat)))
    return target.list_url
