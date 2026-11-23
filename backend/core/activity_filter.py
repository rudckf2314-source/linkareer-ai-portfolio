"""공모전/대외활동 추천 — 과거·마감 데이터 방어 필터."""
from __future__ import annotations

import re
from datetime import date, timedelta

_DATE_RE = re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})")
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_D_MINUS_RE = re.compile(r"D-(\d+)", re.I)
_PAST_EVENT_YEAR_RE = re.compile(
    r"(?<!\d)(20\d{2})\s*(?:년\s*)?(?:오픈|공모|대회|개발자|해커톤|챌린지|대외|아카데미|부트캠프|캠프|페스티벌|컨퍼런스|행사)",
    re.I,
)
_ACTIVE_KW = ("D-", "D-DAY", "D_DAY", "디데이", "상시", "수시", "모집중", "모집 중", "진행중", "진행 중", "오픈")
_PAST_KW = ("D+", "마감 완료", "모집 종료", "접수 마감", "모집마감", "종료됨", "마감된", "마감)")


def today_iso() -> str:
    return date.today().isoformat()


def _parse_iso(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _explicit_dates(blob: str) -> list[date]:
    out: list[date] = []
    for m in _DATE_RE.finditer(blob):
        parsed = _parse_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if parsed:
            out.append(parsed)
    return out


def _d_minus_deadline(blob: str, today: date) -> date | None:
    m = _D_MINUS_RE.search(blob)
    if not m:
        return None
    return today + timedelta(days=int(m.group(1)))


def is_recruiting_activity(
    title: str,
    snippet: str = "",
    *,
    keyword_match: str = "",
    today: date | None = None,
    require_active_signal: bool = False,
) -> bool:
    """오늘 이후 지원 가능한 활동인지 판별. False면 추천에서 제외."""
    today = today or date.today()
    blob = " ".join(x for x in (title, snippet, keyword_match) if x).strip()
    if not blob:
        return False

    upper = blob.upper()
    if any(k in blob for k in _PAST_KW):
        return False
    if "D+" in upper:
        return False

    explicit_dates = _explicit_dates(blob)
    if explicit_dates and max(explicit_dates) >= today and min(explicit_dates) >= today:
        return True

    if re.search(r"마감(?!\s*전)", blob) and "D-" not in upper and not any(k in blob for k in ("상시", "수시", "모집중", "모집 중")):
        return False

    for explicit in explicit_dates:
        if explicit < today:
            return False

    deadline = _d_minus_deadline(blob, today)
    if deadline is not None and deadline < today:
        return False

    years = [int(y) for y in _YEAR_RE.findall(blob)]
    if years and max(years) < today.year:
        return False

    for m in _PAST_EVENT_YEAR_RE.finditer(blob):
        if int(m.group(1)) < today.year:
            return False

    title_stripped = (title or "").strip()
    title_year = re.match(r"^(20\d{2})\b", title_stripped)
    if title_year and int(title_year.group(1)) < today.year:
        return False

    has_active = (
        deadline is not None
        or any(k in blob for k in _ACTIVE_KW)
        or any(d >= today for d in explicit_dates)
        or (years and max(years) >= today.year)
    )
    if require_active_signal and not has_active:
        return False
    return True


def filter_activity_dicts(items: list[dict], *, require_active_signal: bool = False) -> list[dict]:
    """title/snippet 기반 D-Day Hard Rule 필터 (D+ Drop, D-/상시 Pass)."""
    from core.d_day_engine import annotate_d_day, compute_d_day, is_live_item

    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        if not is_live_item(item):
            continue
        info = compute_d_day(item)
        if require_active_signal and info.status == "상시" and info.days_remaining is None:
            blob = _item_blob_for_filter(title, item)
            if "D-" not in blob.upper() and not any(k in blob for k in _ACTIVE_KW):
                continue
        out.append(annotate_d_day(item))
    return out


def _item_blob_for_filter(title: str, item: dict) -> str:
    snippet = str(item.get("snippet") or item.get("content") or "")
    kw = str(item.get("keyword_match") or "")
    return " ".join(x for x in (title, snippet, kw) if x).strip()


_CONTEST_KW = (
    "공모전", "해커톤", "대회", "챌린지", "프로젝트", "대외활동", "서포터즈",
    "아이디어", "경진", "콘테스트", "contest", "hackathon",
)
_TRAINING_KW = (
    "부트캠프", "bootcamp", "훈련과정", "훈련", "k-디지털", "k디지털", "k-digital",
    "내일배움", "일학습병행", "컨소시엄", "사업주훈련", "국민내일배움", "디지털트레이닝",
    "selecttracsedetl", "hrdp", "sw아카데미",
)
_INTERN_KW = (
    "인턴", "인턴십", "신입", "채용", "정규직", "공채", "채용공고", "recruit", "intern",
)
_INTERN_TITLE_RE = re.compile(r"(인턴|인턴십|internship|\bintern\b)", re.I)


def is_strict_internship(item: dict) -> bool:
    """Phase 4 전용 — 인턴·인턴십만 통과 (신입·공채·정규직 제외)."""
    platform = str(item.get("source_platform") or "")
    url = str(item.get("link_url") or item.get("link") or "").lower()

    if "사람인" in platform or "saramin.co.kr" in url:
        return True

    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or item.get("content") or "")
    blob = f"{title} {snippet}"
    return bool(_INTERN_TITLE_RE.search(blob))


def classify_activity_kind(item: dict) -> str:
    """활동 유형 분류: contest|training(Phase3) | internship(Phase4) | other."""
    if item.get("activity_kind") == "training":
        return "training"

    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or item.get("content") or "")
    platform = str(item.get("source_platform") or "")
    url = str(item.get("link_url") or item.get("link") or "")
    blob = f"{title} {snippet} {url} {platform}".lower()

    if any(k in blob for k in _TRAINING_KW):
        return "training"
    if "사람인" in platform or "saramin" in url:
        return "internship"
    if "고용24" in platform or "work24" in url or "worknet" in url:
        if any(k in blob for k in _INTERN_KW):
            return "internship"
        if any(k in blob for k in _TRAINING_KW):
            return "training"
        return "internship"
    if "linkareer" in url or "링커리어" in platform:
        if any(k in blob for k in _INTERN_KW):
            return "internship"
        return "contest"
    if any(k in blob for k in _INTERN_KW):
        return "internship"
    if any(k in blob for k in _CONTEST_KW):
        return "contest"
    return "other"


def filter_source_refs(items: list[dict]) -> list[dict]:
    """로드맵 sources — D+ Drop + d_day 라벨 주입."""
    from core.d_day_engine import annotate_d_day, is_live_item

    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title or not is_live_item(item):
            continue
        out.append(annotate_d_day(item))
    return out
