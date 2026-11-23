"""로드맵 타임라인 → Google Calendar 일정 변환·동기화."""
from __future__ import annotations

import calendar as cal
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from core.models import (
    CalendarEventItem,
    CalendarAddContestRequest,
    CalendarAddContestResponse,
    CalendarSyncRequest,
    CalendarSyncResponse,
)
from tools.google_calendar_tool import GoogleCalendarError, google_calendar_tool

_KST = timezone(timedelta(hours=9))
_DATE_RE = re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_PERIOD_RE = re.compile(r"(\d+)\s*[-~]\s*(\d+)\s*개월")
_SINGLE_MONTH_RE = re.compile(r"(\d+)\s*개월")


def _parse_period(period: str) -> tuple[int | None, int | None]:
    text = period or ""
    m = _PERIOD_RE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _SINGLE_MONTH_RE.search(text)
    if m:
        n = int(m.group(1))
        return n, n
    return None, None


def _add_months(d: date, months: int) -> date:
    if months <= 0:
        return d
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = cal.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _phase_date_ranges(phases: list[dict], start: date) -> list[tuple[date, date]]:
    """period.to 를 누적 마일스톤으로 해석해 Phase별 (start, end) 날짜를 계산."""
    ranges: list[tuple[date, date]] = []
    prev_end: date | None = None
    cumulative_to = 0

    for phase in phases:
        _, to_m = _parse_period(str(phase.get("period") or ""))
        if to_m is None:
            cumulative_to += 1
        else:
            cumulative_to = max(cumulative_to, to_m)

        phase_start = (prev_end + timedelta(days=1)) if prev_end else start
        phase_end = _add_months(start, cumulative_to)
        if phase_end <= phase_start:
            phase_end = phase_start + timedelta(days=14)
        ranges.append((phase_start, phase_end))
        prev_end = phase_end

    return ranges


def _roadmap_tag(company: str, job: str) -> str:
    raw = f"career-hub|{company.strip()}|{job.strip()}"
    return re.sub(r"[^\w|가-힣\-]", "_", raw)[:120]


def _normalize_phases(roadmap_result: dict) -> list[dict]:
    timeline = roadmap_result.get("timeline") or []
    if timeline:
        return sorted(timeline, key=lambda p: p.get("phase_num") or 0)
    legacy = roadmap_result.get("structured_roadmap") or []
    out = []
    for i, step in enumerate(legacy):
        out.append({
            "phase_num": i + 1,
            "phase_title": step.get("phase_title") or step.get("phase") or f"Phase {i + 1}",
            "period": step.get("period") or step.get("phase") or "",
            "actions": step.get("action_items") or step.get("actions") or [],
            "sources": step.get("recommended_activities") or step.get("sources") or [],
            "expected_outcome": step.get("expected_outcome") or "",
            "narrative_bridge_directive": step.get("narrative_bridge_directive") or "",
            "required_certifications": step.get("required_certifications") or [],
        })
    return out


def _format_description(phase: dict, meta: dict) -> str:
    lines = [
        f"{meta['company']} · {meta['job']} ({meta['field']})",
        f"Phase {phase.get('phase_num', '?')} — {phase.get('period', '')}",
        "",
    ]
    directive = phase.get("narrative_bridge_directive") or ""
    if directive:
        lines.extend(["[서사 지침]", directive, ""])

    actions = phase.get("actions") or []
    if actions:
        lines.append("[액션]")
        lines.extend(f"• {a}" for a in actions)
        lines.append("")

    sources = phase.get("sources") or []
    if sources:
        lines.append("[추천 활동 / 소싱]")
        for src in sources:
            title = src.get("title") or ""
            platform = src.get("source_platform") or ""
            url = src.get("link_url") or ""
            match = src.get("keyword_match") or ""
            line = f"• [{platform}] {title}"
            if match:
                line += f" — {match}"
            if url:
                line += f"\n  {url}"
            lines.append(line)
        lines.append("")

    certs = phase.get("required_certifications") or []
    if certs:
        lines.append("[자격증]")
        for c in certs:
            name = c if isinstance(c, str) else c.get("name", "")
            if name:
                lines.append(f"• {name}")

    outcome = phase.get("expected_outcome") or ""
    if outcome:
        lines.extend(["", "[기대 성과]", outcome])

    lines.append("")
    lines.append("— Linkareer AI Career Hub")
    return "\n".join(lines)


def _parse_contest_date(date_str: str) -> date:
    text = (date_str or "").strip()
    if not _DATE_RE.match(text):
        raise GoogleCalendarError("date는 YYYY-MM-DD 형식이어야 합니다.")
    y, m, d = (int(x) for x in text.split("-"))
    return date(y, m, d)


def _contest_event_body(title: str, url: str, deadline: date) -> dict:
    start_dt = f"{deadline.isoformat()}T11:00:00"
    end_dt = f"{deadline.isoformat()}T12:00:00"
    summary = f"[마감] {title.strip()}"[:200]
    desc_lines = [f"공모전/대외활동 마감 알림 — {deadline.isoformat()}", ""]
    if url.strip():
        desc_lines.extend(["[상세 링크]", url.strip(), ""])
    desc_lines.append("— Linkareer AI Career Hub")
    return {
        "summary": summary,
        "description": "\n".join(desc_lines)[:8000],
        "start": {"dateTime": start_dt, "timeZone": "Asia/Seoul"},
        "end": {"dateTime": end_dt, "timeZone": "Asia/Seoul"},
        "extendedProperties": {
            "private": {
                "source": "career-hub",
                "event_type": "contest_deadline",
            }
        },
    }


def _event_body(
    phase: dict,
    start: date,
    end: date,
    tag: str,
    meta: dict,
) -> dict:
    phase_num = phase.get("phase_num") or 0
    title = phase.get("phase_title") or f"Phase {phase_num}"
    summary = f"[커리어로드맵 P{phase_num}] {title}"
    # Google Calendar all-day: end date is exclusive
    return {
        "summary": summary[:200],
        "description": _format_description(phase, meta)[:8000],
        "start": {"date": start.isoformat()},
        "end": {"date": (end + timedelta(days=1)).isoformat()},
        "extendedProperties": {
            "private": {
                "roadmap_tag": tag,
                "phase_num": str(phase_num),
                "source": "career-hub",
            }
        },
    }


class CalendarService:
    """로드맵 결과를 Google Calendar에 동기화."""

    def __init__(self) -> None:
        self._tool = google_calendar_tool

    def status(self) -> dict:
        return {
            "configured": self._tool.is_configured(),
            "calendar_id": self._tool._calendar_id,
        }

    def sync_roadmap(self, payload: CalendarSyncRequest) -> CalendarSyncResponse:
        if not self._tool.is_configured():
            raise GoogleCalendarError(
                "Google Calendar 미설정. python scripts/google_calendar_auth.py 실행 후 "
                "GOOGLE_REFRESH_TOKEN을 .env에 추가하세요."
            )
        if not payload.roadmap_result:
            raise GoogleCalendarError("roadmap_result가 비어 있습니다.")

        phases = _normalize_phases(payload.roadmap_result)
        if not phases:
            raise GoogleCalendarError("동기화할 타임라인 Phase가 없습니다.")

        tag = _roadmap_tag(payload.target_company, payload.target_job)
        start_date = date.today()
        ranges = _phase_date_ranges(phases, start_date)
        meta = {
            "company": payload.target_company.strip(),
            "job": payload.target_job.strip(),
            "field": payload.target_field.strip(),
            "user": payload.user_name.strip(),
        }

        deleted = 0
        if payload.replace_existing:
            time_min = datetime.combine(start_date, datetime.min.time(), tzinfo=_KST).isoformat()
            for ev in self._tool.list_events_by_tag(tag, time_min=time_min):
                self._tool.delete_event(ev["id"])
                deleted += 1

        created: list[CalendarEventItem] = []
        for phase, (p_start, p_end) in zip(phases, ranges):
            body = _event_body(phase, p_start, p_end, tag, meta)
            result = self._tool.create_event(body)
            created.append(
                CalendarEventItem(
                    event_id=result.get("id", ""),
                    title=result.get("summary", body["summary"]),
                    start=p_start.isoformat(),
                    end=p_end.isoformat(),
                    html_link=result.get("htmlLink"),
                )
            )

        return CalendarSyncResponse(
            success=True,
            calendar_id=self._tool._calendar_id,
            created_count=len(created),
            deleted_count=deleted,
            events=created,
            message=f"{payload.target_company} · {payload.target_job} 로드맵 {len(created)}개 Phase 일정을 등록했습니다.",
        )

    def add_contest(self, payload: CalendarAddContestRequest) -> CalendarAddContestResponse:
        if not self._tool.is_configured():
            raise GoogleCalendarError(
                "Google Calendar 미설정. GOOGLE_REFRESH_TOKEN을 .env에 추가하세요."
            )
        title = payload.title.strip()
        if not title:
            raise GoogleCalendarError("title은 필수입니다.")
        deadline = _parse_contest_date(payload.date)
        body = _contest_event_body(title, payload.url, deadline)
        result = self._tool.create_event(body)
        start = body["start"]["dateTime"]
        end = body["end"]["dateTime"]
        return CalendarAddContestResponse(
            success=True,
            calendar_id=self._tool._calendar_id,
            event_id=result.get("id", ""),
            title=result.get("summary", body["summary"]),
            start=start,
            end=end,
            html_link=result.get("htmlLink"),
            message="대외활동 마감 일정이 캘린더(오전 11시)에 등록되었습니다!",
        )


calendar_service = CalendarService()
