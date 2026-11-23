"""고용24(Work24) 분야·직무 기반 부트캠프/훈련과정 검색 — Phase 3 소싱용."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import requests

from core.config import settings

TRAINING_SOURCES = {
    "nbc": {
        "label": "국민내일배움카드",
        "key_attr": "WORKNET_API_KEY_TRAINING_NBC",
        "url": "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo310L01.do",
    },
    "biz": {
        "label": "사업주훈련",
        "key_attr": "WORKNET_API_KEY_TRAINING_BIZ",
        "url": "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo311L01.do",
    },
    "consortium": {
        "label": "컨소시엄",
        "key_attr": "WORKNET_API_KEY_TRAINING_CONSORTIUM",
        "url": "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo312L01.do",
    },
    "work_study": {
        "label": "일학습병행",
        "key_attr": "WORKNET_API_KEY_TRAINING_WORK",
        "url": "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo313L01.do",
    },
}

BOOTCAMP_TRAIN_TYPES = {
    "C0104": "K-디지털 트레이닝",
    "C0105": "K-디지털 기초역량훈련",
    "C0102": "산업구조변화대응",
    "C0054": "국가기간전략산업직종",
    "C0055C": "과정평가형훈련",
    "C0054G": "기업맞춤형훈련",
    "C0061": "국민내일배움카드(일반)",
    "C0061S": "국민내일배움카드(구직자)",
}
BOOTCAMP_KEYWORDS = ("부트캠프", "아카데미", "양성", "캠프", "트레이닝", "K-디지털", "k-디지털")


@dataclass
class TrainingCourse:
    title: str
    institution: str
    start_date: str
    end_date: str
    address: str
    cost: str
    train_target: str
    train_target_code: str
    link: str
    source: str
    course_id: str
    score: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)


def _default_date_range() -> tuple[str, str]:
    today = date.today()
    end = today + timedelta(days=365)
    return today.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _fmt_date(raw: str) -> str:
    raw = (raw or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def _parse_date(raw: str) -> date | None:
    fmt = _fmt_date(raw)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", fmt)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _course_duration_days(start: str, end: str) -> int:
    s, e = _parse_date(start), _parse_date(end)
    if not s or not e:
        return 0
    return max((e - s).days, 0)


def _build_search_keywords(field: str, job: str) -> list[str]:
    field = field.strip()
    job = job.strip()
    keywords: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in keywords:
            keywords.append(value)

    add(field)
    add(job)
    if field and job:
        add(f"{field} {job}")
        add(f"{field}{job}")
        add(f"{job} {field}")
        add(f"{field} {job} 부트캠프")
        add(f"{field} 부트캠프")
        add(f"{job} 부트캠프")
        add(f"{field} {job} 아카데미")
        add(f"{field} {job} 양성")
    return keywords


def _score_course(item: dict[str, Any], field: str, job: str, keyword: str) -> tuple[float, list[str]]:
    title = _normalize_text(item.get("title") or "")
    institution = _normalize_text(item.get("subTitle") or "")
    target = _normalize_text(item.get("trainTarget") or "")
    combined = f"{title} {institution} {target}"

    score = 0.0
    matched: list[str] = []

    field_term = _normalize_text(field)
    if field_term and field_term in combined:
        score += 4.0
        matched.append(field)

    job_term = _normalize_text(job)
    if job_term:
        if job_term in combined:
            score += 3.0
            matched.append(job)
        else:
            tokens = [t for t in re.split(r"\s+", job_term) if len(t) >= 2]
            hits = sum(1 for t in tokens if t in combined)
            if hits:
                score += min(hits * 1.2, 2.5)
                matched.append(job)

    kw_term = _normalize_text(keyword)
    if kw_term and kw_term in combined:
        score += 1.5
        matched.append(keyword)

    for marker in BOOTCAMP_KEYWORDS:
        if marker.lower() in combined:
            score += 2.5
            matched.append(marker)
            break

    train_code = item.get("trainTargetCd") or ""
    if train_code in BOOTCAMP_TRAIN_TYPES:
        score += 2.0
        matched.append(BOOTCAMP_TRAIN_TYPES[train_code])

    duration = _course_duration_days(item.get("traStartDate") or "", item.get("traEndDate") or "")
    if duration >= 60:
        score += 2.0
    elif duration >= 30:
        score += 1.0

    return score, sorted(set(matched))


def _raw_to_course(
    item: dict[str, Any],
    source_key: str,
    score: float,
    matched_keywords: list[str],
) -> TrainingCourse:
    return TrainingCourse(
        title=item.get("title") or "",
        institution=item.get("subTitle") or "",
        start_date=item.get("traStartDate") or "",
        end_date=item.get("traEndDate") or "",
        address=item.get("address") or "",
        cost=item.get("realMan") or "",
        train_target=item.get("trainTarget") or "",
        train_target_code=item.get("trainTargetCd") or "",
        link=item.get("titleLink") or "",
        source=TRAINING_SOURCES[source_key]["label"],
        course_id=item.get("trprId") or "",
        score=round(score, 2),
        matched_keywords=matched_keywords,
    )


class Work24TrainingClient:
    def search(
        self,
        source_key: str,
        keyword: str | None = None,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        train_type: str | None = None,
        page_size: int = 30,
    ) -> list[dict[str, Any]]:
        source = TRAINING_SOURCES[source_key]
        api_key = getattr(settings, source["key_attr"], None)
        if not api_key:
            return []

        if not start_date or not end_date:
            start_date, end_date = _default_date_range()

        params: dict[str, str] = {
            "authKey": api_key,
            "returnType": "JSON",
            "outType": "1",
            "pageNum": "1",
            "pageSize": str(page_size),
            "srchTraStDt": start_date,
            "srchTraEndDt": end_date,
            "sort": "ASC",
            "sortCol": "2",
        }
        if keyword:
            params["srchTraProcessNm"] = keyword
        if train_type:
            params["crseTracseSe"] = train_type

        try:
            res = requests.get(source["url"], params=params, timeout=20)
            res.raise_for_status()
            data = res.json()
        except Exception:
            return []

        if data.get("error"):
            return []
        return data.get("srchList") or []


def search_training_programs(
    field: str,
    job: str,
    *,
    top_n: int = 8,
    bootcamp_only: bool = False,
) -> list[TrainingCourse]:
    """분야·직무 키워드로 고용24 훈련과정 검색 후 스코어·중복 제거."""
    if not field.strip() and not job.strip():
        return []

    client = Work24TrainingClient()
    start_date, end_date = _default_date_range()
    keywords = _build_search_keywords(field, job)[:5]

    query_specs: list[tuple[str, str | None]] = [(kw, None) for kw in keywords]
    if bootcamp_only:
        for train_type in ("C0104", "C0105"):
            query_specs.append((field, train_type))

    merged: dict[str, TrainingCourse] = {}
    tasks: list[tuple[str, str, str | None]] = []
    for source_key in TRAINING_SOURCES:
        for keyword, train_type in query_specs:
            tasks.append((source_key, keyword, train_type))

    def _fetch_one(source_key: str, keyword: str, train_type: str | None) -> list[dict]:
        return client.search(
            source_key,
            keyword=keyword or None,
            start_date=start_date,
            end_date=end_date,
            train_type=train_type,
            page_size=20,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_fetch_one, sk, kw, tt): (sk, kw, tt)
            for sk, kw, tt in tasks
        }
        for fut in as_completed(futures):
            source_key, keyword, _ = futures[fut]
            try:
                items = fut.result()
            except Exception:
                continue
            for item in items:
                score, matched = _score_course(item, field, job, keyword or "")
                if score <= 0:
                    continue
                if bootcamp_only:
                    combined = _normalize_text(
                        f"{item.get('title') or ''} {item.get('subTitle') or ''} {item.get('trainTarget') or ''}"
                    )
                    if _normalize_text(field) not in combined and _normalize_text(job) not in combined:
                        continue
                end = _parse_date(item.get("traEndDate") or "")
                if end and end < date.today():
                    continue
                course = _raw_to_course(item, source_key, score, matched)
                key = course.course_id or f"{course.title}|{course.institution}|{course.start_date}"
                existing = merged.get(key)
                if existing is None or course.score > existing.score:
                    merged[key] = course
            if len(merged) >= top_n * 3:
                break

    results = sorted(merged.values(), key=lambda c: (-c.score, c.start_date))
    return results[:top_n]


def courses_to_activities(courses: list[TrainingCourse], *, field: str = "", job: str = "") -> list[dict]:
    """TrainingCourse → roadmap activity dict (Phase 3 소싱 풀)."""
    activities: list[dict] = []
    for c in courses:
        start_fmt = _fmt_date(c.start_date)
        end_fmt = _fmt_date(c.end_date)
        kw_match = ", ".join(c.matched_keywords[:3]) or f"{field} {job}".strip()
        snippet_parts = [p for p in (c.institution, c.train_target, c.address) if p]
        if c.cost:
            snippet_parts.append(f"비용:{c.cost}원")
        snippet = " | ".join(snippet_parts)
        if start_fmt or end_fmt:
            snippet = f"{start_fmt}~{end_fmt} | {snippet}" if snippet else f"{start_fmt}~{end_fmt}"

        activities.append({
            "source_platform": f"고용24({c.source})",
            "title": c.title,
            "link_url": c.link or None,
            "keyword_match": kw_match,
            "snippet": snippet[:300],
            "start_date": start_fmt,
            "end_date": end_fmt,
            "deadline": start_fmt or end_fmt,
            "activity_kind": "training",
        })
    return activities


class TrainingSearchService:
    """Phase 3 부트캠프/훈련 소싱 진입점."""

    def search_as_activities(self, field: str, job: str, *, top_n: int = 8) -> list[dict]:
        courses = search_training_programs(field, job, top_n=top_n, bootcamp_only=False)
        return courses_to_activities(courses, field=field, job=job)


training_search_service = TrainingSearchService()
