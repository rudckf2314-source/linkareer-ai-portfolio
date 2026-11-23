"""
[D-Day Rule Engine] 실시간 마감 연산 · D+ Drop · D-/상시 Pass · 임박순 정렬.

Hard Rule:
  - D+ / 마감됨 → 즉시 Drop
  - D- / 상시 → Pass, 마감 임박순 정렬
  - 유효 공고 부족 시 recommendation_engine 직무>분야 Fallback
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from core.activity_filter import _ACTIVE_KW, _DATE_RE, _D_MINUS_RE, _PAST_KW, _explicit_dates

_META_PATH = Path(__file__).resolve().parent.parent / "cache" / "recommendation_meta.json"

DDayStatus = Literal["D-", "D+", "상시"]
_SORT_ONGOING = 9999  # 상시모집 정렬 시 맨 뒤


@dataclass(frozen=True)
class DDayInfo:
    status: DDayStatus
    label: str
    days_remaining: int | None
    deadline: date | None


def _load_d_day_config() -> dict:
    defaults = {
        "min_live_items": 3,
        "sort_ongoing_last": True,
        "drop_statuses": ["D+"],
    }
    if _META_PATH.is_file():
        try:
            meta = json.loads(_META_PATH.read_text(encoding="utf-8"))
            return {**defaults, **(meta.get("d_day_rules") or {})}
        except Exception:
            pass
    return defaults


def _item_blob(item: dict) -> str:
    return " ".join(filter(None, [
        item.get("title", ""),
        item.get("snippet", ""),
        item.get("content", ""),
        item.get("keyword_match", ""),
        item.get("deadline", ""),
        item.get("deadline_date", ""),
        item.get("end_date", ""),
    ])).strip()


def compute_d_day(item: dict, *, today: date | None = None) -> DDayInfo:
    """공고 1건의 D-Day 상태 연산."""
    today = today or date.today()
    blob = _item_blob(item)
    upper = blob.upper()

    if any(k in blob for k in _PAST_KW):
        return DDayInfo("D+", "마감", 0, None)
    if "D+" in upper or re.search(r"D\s*\+\s*\d+", upper):
        m = re.search(r"D\s*\+\s*(\d+)", upper)
        n = int(m.group(1)) if m else 0
        return DDayInfo("D+", f"D+{n}", -n, None)

    m = _D_MINUS_RE.search(blob)
    if m:
        days = int(m.group(1))
        deadline = today + timedelta(days=days)
        return DDayInfo("D-", f"D-{days}", days, deadline)

    if re.search(r"D\s*-\s*DAY|D_DAY|디데이", upper):
        return DDayInfo("D-", "D-DAY", 0, today)

    if re.search(r"오늘\s*마감|금일\s*마감", blob):
        return DDayInfo("D-", "D-DAY", 0, today)

    if any(k in blob for k in ("상시", "수시", "상시모집", "수시모집", "상시 채용", "상시모집")):
        return DDayInfo("상시", "상시모집", None, None)

    if any(k in blob for k in _ACTIVE_KW) and "마감" not in blob:
        return DDayInfo("상시", "상시모집", None, None)

    explicit = _explicit_dates(blob)
    if explicit:
        deadline = max(explicit)
        delta = (deadline - today).days
        if delta < 0:
            return DDayInfo("D+", f"D+{abs(delta)}", delta, deadline)
        if delta == 0:
            return DDayInfo("D-", "D-DAY", 0, deadline)
        return DDayInfo("D-", f"D-{delta}", delta, deadline)

    end_raw = item.get("end_date") or item.get("deadline") or item.get("deadline_date")
    if end_raw:
        dates = _explicit_dates(str(end_raw))
        if dates:
            deadline = max(dates)
            delta = (deadline - today).days
            if delta < 0:
                return DDayInfo("D+", f"D+{abs(delta)}", delta, deadline)
            return DDayInfo("D-", f"D-{delta}", delta, deadline)

    if re.search(r"마감(?!\s*전)", blob) and "D-" not in upper:
        return DDayInfo("D+", "마감", 0, None)

    # 신호 없음 — 보수적으로 Drop (로드맵 live 링크만 노출 원칙)
    return DDayInfo("D+", "미확인", None, None)


def is_live_item(item: dict, *, today: date | None = None) -> bool:
    return compute_d_day(item, today=today).status != "D+"


def format_deadline_display(d: date) -> str:
    """UI용 한국어 마감일 (예: 2026년 6월 14일 (일))."""
    weekdays = "월화수목금토일"
    return f"{d.year}년 {d.month}월 {d.day}일 ({weekdays[d.weekday()]})"


def annotate_d_day(item: dict, *, today: date | None = None) -> dict:
    """d_day_status, d_day_label, days_remaining, deadline, deadline_display 필드 주입."""
    info = compute_d_day(item, today=today)
    out = dict(item)
    out["d_day_status"] = info.status
    out["d_day_label"] = info.label
    out["days_remaining"] = info.days_remaining
    if info.deadline:
        iso = info.deadline.isoformat()
        out["deadline"] = iso
        out["deadline_date"] = iso
        out["deadline_display"] = format_deadline_display(info.deadline)
    elif info.status == "상시":
        out["deadline_display"] = "채용 시까지"
    else:
        out["deadline_display"] = ""
    out["is_live"] = info.status != "D+"
    return out


def drop_expired(items: list[dict], *, today: date | None = None) -> list[dict]:
    """규칙 2: D+ 즉시 Drop."""
    return [annotate_d_day(it, today=today) for it in items if is_live_item(it, today=today)]


def sort_by_urgency(items: list[dict], *, ongoing_last: bool = True) -> list[dict]:
    """규칙 1: D-1 → D-3 → … → 상시 순."""

    def _key(it: dict) -> tuple:
        status = it.get("d_day_status", "D+")
        if status == "상시":
            days = _SORT_ONGOING if ongoing_last else 0
        else:
            days = it.get("days_remaining")
            if days is None:
                days = _SORT_ONGOING
        score = -(it.get("matching_score") or 0)
        return (days, score)

    return sorted(items, key=_key)


def filter_live_recommendations(
    items: list[dict],
    *,
    min_required: int | None = None,
    today: date | None = None,
) -> tuple[list[dict], dict]:
    """
    D-Day Hard Rule 파이프라인:
      1) D+ Drop
      2) 임박순 정렬
      3) 메타 반환 (drop 수 등)
    """
    cfg = _load_d_day_config()
    min_req = min_required if min_required is not None else int(cfg.get("min_live_items", 3))
    today = today or date.today()

    dropped = 0
    live: list[dict] = []
    for it in items or []:
        info = compute_d_day(it, today=today)
        if info.status == "D+":
            dropped += 1
            continue
        live.append(annotate_d_day(it, today=today))

    live = sort_by_urgency(live, ongoing_last=bool(cfg.get("sort_ongoing_last", True)))
    meta = {
        "input_count": len(items or []),
        "live_count": len(live),
        "dropped_expired": dropped,
        "min_required": min_req,
        "needs_fallback": len(live) < min_req,
    }
    return live, meta
