"""Google Calendar 로드맵 동기화 API (서버 내부 OAuth, UI 로그인 없음)."""
from fastapi import APIRouter, HTTPException

from core.models import CalendarAddContestRequest, CalendarAddContestResponse, CalendarSyncRequest, CalendarSyncResponse
from services.calendar_service import calendar_service
from tools.google_calendar_tool import GoogleCalendarError

router = APIRouter(prefix="/api/calendar", tags=["Google Calendar"])


@router.get("/status")
async def calendar_status():
    """Calendar 연동 설정 여부 확인."""
    return calendar_service.status()


@router.post("/sync-roadmap", response_model=CalendarSyncResponse)
async def sync_roadmap_to_calendar(payload: CalendarSyncRequest):
    """완성된 4-Phase 로드맵을 Google Calendar에 일정으로 등록."""
    if not (payload.target_field.strip() and payload.target_company.strip() and payload.target_job.strip()):
        raise HTTPException(status_code=400, detail="target_field, target_company, target_job는 필수입니다.")
    if not payload.roadmap_result:
        raise HTTPException(status_code=400, detail="roadmap_result(로드맵 결과)가 비어 있습니다.")
    try:
        return calendar_service.sync_roadmap(payload)
    except GoogleCalendarError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"캘린더 동기화 실패: {exc}") from exc


@router.post("/add-contest", response_model=CalendarAddContestResponse)
async def add_contest_to_calendar(payload: CalendarAddContestRequest):
    """공모전/대외활동 마감일을 Google Calendar에 오전 11시 일정으로 등록."""
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="title은 필수입니다.")
    if not payload.date.strip():
        raise HTTPException(status_code=400, detail="date(마감일)는 필수입니다.")
    try:
        return calendar_service.add_contest(payload)
    except GoogleCalendarError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"캘린더 등록 실패: {exc}") from exc
