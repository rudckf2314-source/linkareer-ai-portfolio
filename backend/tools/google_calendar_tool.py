"""Google Calendar API 연동 도구 (서버 내부 refresh token 인증)."""
from __future__ import annotations

from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from core.config import settings
from tools.base_tool import BaseTool

SCOPES = ("https://www.googleapis.com/auth/calendar.events",)
TOKEN_URI = "https://oauth2.googleapis.com/token"


class GoogleCalendarError(Exception):
    """Google Calendar API 호출 실패."""


class GoogleCalendarTool(BaseTool):
    """refresh token 기반 Google Calendar 이벤트 CRUD."""

    name = "google_calendar_tool"

    def __init__(self) -> None:
        self._calendar_id = settings.GOOGLE_CALENDAR_ID

    @staticmethod
    def is_configured() -> bool:
        return settings.google_calendar_ready

    def _credentials(self) -> Credentials:
        if not self.is_configured():
            raise GoogleCalendarError(
                "Google Calendar가 설정되지 않았습니다. "
                "scripts/google_calendar_auth.py 로 refresh token을 발급한 뒤 "
                "GOOGLE_REFRESH_TOKEN을 .env에 추가하세요."
            )
        creds = Credentials(
            token=None,
            refresh_token=settings.GOOGLE_REFRESH_TOKEN,
            token_uri=TOKEN_URI,
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=list(SCOPES),
        )
        creds.refresh(Request())
        return creds

    def _service(self):
        return build("calendar", "v3", credentials=self._credentials(), cache_discovery=False)

    def list_events_by_tag(self, tag: str, time_min: str | None = None) -> list[dict]:
        """extendedProperties.private.roadmap_tag 로 기존 로드맵 일정 조회."""
        try:
            svc = self._service()
            params: dict[str, Any] = {
                "calendarId": self._calendar_id,
                "privateExtendedProperty": f"roadmap_tag={tag}",
                "singleEvents": True,
                "maxResults": 250,
            }
            if time_min:
                params["timeMin"] = time_min
            result = svc.events().list(**params).execute()
            return result.get("items", [])
        except HttpError as exc:
            raise GoogleCalendarError(f"일정 조회 실패: {exc}") from exc

    def delete_event(self, event_id: str) -> None:
        try:
            self._service().events().delete(
                calendarId=self._calendar_id,
                eventId=event_id,
            ).execute()
        except HttpError as exc:
            if exc.resp.status != 404:
                raise GoogleCalendarError(f"일정 삭제 실패: {exc}") from exc

    def create_event(self, body: dict) -> dict:
        try:
            return (
                self._service()
                .events()
                .insert(calendarId=self._calendar_id, body=body)
                .execute()
            )
        except HttpError as exc:
            raise GoogleCalendarError(f"일정 생성 실패: {exc}") from exc

    def execute(self, query: str, **kwargs: Any) -> Any:
        action = kwargs.get("action", query)
        if action == "list_by_tag":
            return self.list_events_by_tag(kwargs["tag"], kwargs.get("time_min"))
        if action == "create":
            return self.create_event(kwargs["body"])
        if action == "delete":
            self.delete_event(kwargs["event_id"])
            return {"deleted": kwargs["event_id"]}
        raise GoogleCalendarError(f"지원하지 않는 action: {action}")


google_calendar_tool = GoogleCalendarTool()
