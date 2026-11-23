"""링커리어 기업분석 자료 — 최신본 선택 및 계열사 Strict/Fallback 매칭."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MatchType = Literal["strict", "parent_fallback", "brand_partial", "none"]

_PERIOD_RE = re.compile(
    r"(20\d{2})\s*년?\s*(상반기|하반기)"
    r"|(20\d{2})\s*(상반기|하반기)"
    r"|(20\d{2})\s*년"
)
_SUBSIDIARY_RE = re.compile(r"([^(]+)\(([^)]+)\)")
_COMPANY_ANALYSIS_URL_RE = re.compile(
    r"https?://(?:www\.)?linkareer\.com/company-analysis/(\d+)",
    re.I,
)

KEY_FEATURES = [
    "기업핵심파악(사업영역/재무상태)",
    "최신이슈 및 전략 전망",
    "실제 면접 기출문제 및 모범답안 해설",
]


@dataclass(frozen=True)
class CompanyIdentity:
    raw: str
    base: str
    unit: str | None


@dataclass
class AnalysisCandidate:
    title: str
    url: str
    snippet: str = ""
    company_score: float = 0.0
    match_type: MatchType = "none"
    period_year: int = 0
    period_half: int = 0
    is_latest: bool = False


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _parse_identity(name: str) -> CompanyIdentity:
    raw = (name or "").strip()
    m = _SUBSIDIARY_RE.search(raw)
    if m:
        return CompanyIdentity(raw=raw, base=m.group(1).strip(), unit=m.group(2).strip())
    return CompanyIdentity(raw=raw, base=raw, unit=None)


def parse_archive_period(title: str) -> tuple[int, int]:
    """(year, half) — half: 2=하반기, 1=상반기, 0=연도만."""
    blob = title or ""
    m = _PERIOD_RE.search(blob)
    if not m:
        return 0, 0
    groups = [g for g in m.groups() if g]
    if len(groups) >= 2 and groups[1] in ("상반기", "하반기"):
        year = int(groups[0])
        half = 2 if groups[1] == "하반기" else 1
        return year, half
    if groups and groups[0].isdigit() and len(groups[0]) == 4:
        return int(groups[0]), 0
    return 0, 0


def period_sort_key(year: int, half: int) -> int:
    """큰 값일수록 최신 (2026 하반기 > 2026 상반기 > 2025 하반기)."""
    return year * 10 + half


def normalize_viewer_url(url: str) -> str | None:
    m = _COMPANY_ANALYSIS_URL_RE.search(url or "")
    if not m:
        return None
    return f"https://linkareer.com/company-analysis/{m.group(1)}"


def score_company_match(target_company: str, archive_title: str) -> tuple[float, MatchType]:
    """
    Strict Match: 동일 계열사(예: 삼성전자(DS)) → 100점
    Parent Fallback: 세부 계열사 자료 없을 때 모기업/대표군 → 72점
    Brand Partial: 브랜드 토큰만 일치 → 45점
    """
    target = _parse_identity(target_company)
    title_id = _parse_identity(archive_title)
    t_base = _norm(target.base)
    t_unit = _norm(target.unit) if target.unit else None
    a_base = _norm(title_id.base)
    a_unit = _norm(title_id.unit) if title_id.unit else None
    blob = _norm(archive_title)

    if not t_base:
        return 0.0, "none"

    if t_base == a_base:
        if t_unit and a_unit:
            return (100.0, "strict") if t_unit == a_unit else (25.0, "none")
        if t_unit and not a_unit:
            return 72.0, "parent_fallback"
        if not t_unit and a_unit:
            return 55.0, "brand_partial"
        return 95.0, "strict"

    if t_base in blob or blob.startswith(t_base[: max(2, len(t_base) - 1)]):
        if t_unit and a_unit and t_unit == a_unit:
            return 88.0, "strict"
        if t_unit and not a_unit:
            return 68.0, "parent_fallback"
        return 45.0, "brand_partial"

    # 모기업 토큰(앞 2~4글자) 기반 완화
    prefix = t_base[: min(4, len(t_base))]
    if len(prefix) >= 2 and prefix in blob:
        return 40.0, "brand_partial"

    return 0.0, "none"


def rank_company_analysis_candidates(
    items: list[dict],
    *,
    target_company: str,
    target_field: str = "",
    target_job: str = "",
    min_score: float = 40.0,
) -> list[AnalysisCandidate]:
    """수집 리스트 → 기업 매칭 점수 + 최신 기간 정렬."""
    candidates: list[AnalysisCandidate] = []
    for item in items or []:
        title = str(item.get("title") or "").split(" | ")[0].strip()
        url = normalize_viewer_url(str(item.get("url") or item.get("link") or ""))
        if not title or not url:
            continue
        score, match_type = score_company_match(target_company, title)
        if score < min_score:
            continue
        year, half = parse_archive_period(title)
        candidates.append(AnalysisCandidate(
            title=title,
            url=url,
            snippet=str(item.get("snippet") or item.get("content") or "")[:400],
            company_score=score,
            match_type=match_type,
            period_year=year,
            period_half=half,
        ))

    if not candidates:
        return []

    max_period = max(period_sort_key(c.period_year, c.period_half) for c in candidates)
    for c in candidates:
        c.is_latest = period_sort_key(c.period_year, c.period_half) == max_period and max_period > 0

    candidates.sort(
        key=lambda c: (
            -c.company_score,
            -period_sort_key(c.period_year, c.period_half),
            0 if c.match_type == "strict" else 1,
        ),
    )
    return candidates


def build_corporate_analysis_payload(
    candidate: AnalysisCandidate | None,
    *,
    target_company: str,
    target_job: str,
    target_field: str = "",
) -> dict:
    """프론트엔드·대시보드용 정형 JSON."""
    if not candidate:
        return {
            "search_context": {
                "target_company": target_company,
                "target_job": target_job,
                "target_field": target_field,
            },
            "corporate_analysis_content": {
                "has_data": False,
                "company_full_name": target_company,
                "archive_title": "",
                "key_features": KEY_FEATURES,
                "target_viewer_url": "",
                "is_latest": False,
                "match_type": "none",
                "company_match_score": 0,
            },
        }

    return {
        "search_context": {
            "target_company": target_company,
            "target_job": target_job,
            "target_field": target_field,
        },
        "corporate_analysis_content": {
            "has_data": True,
            "company_full_name": target_company,
            "archive_title": candidate.title,
            "key_features": KEY_FEATURES,
            "target_viewer_url": candidate.url,
            "is_latest": candidate.is_latest,
            "match_type": candidate.match_type,
            "company_match_score": round(candidate.company_score, 1),
            "period_label": (
                f"{candidate.period_year}년 "
                + ("상반기" if candidate.period_half == 1 else "하반기" if candidate.period_half == 2 else "")
            ).strip() if candidate.period_year else "",
        },
    }
