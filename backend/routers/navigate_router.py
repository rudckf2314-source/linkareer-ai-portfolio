"""[Controller Layer] AI Agent형 UI 자동 제어(RPA) 네비게이션 라우터."""
from fastapi import APIRouter, HTTPException

from core.navigate_models import NavigateRequest, NavigateResponse
from services.navigate_service import navigate_service

router = APIRouter(prefix="/api/chat", tags=["navigate"])


@router.post("/navigate", response_model=NavigateResponse)
async def navigate(request: NavigateRequest) -> NavigateResponse:
    """
    챗봇 ↔ 희망 직무 탐색 UI 자동 제어(RPA) 엔드포인트.

    - 사용자 메시지와 현재 UI 필터 상태를 받아
    - OpenAI Function Calling으로 의도를 분석한 뒤
    - 대화 응답(reply)과 UI 조작 명령(ui_control)을 동시에 반환합니다.

    Args:
        request: NavigateRequest
            - message: 사용자 입력 메시지
            - chat_history: 이전 대화 히스토리
            - current_filter_state: 현재 프론트엔드 UI 필터 상태 (양방향 동기화)
            - user_spec_summary: 사용자 스펙 요약 (선택)

    Returns:
        NavigateResponse
            - reply: 챗봇 대화 응답
            - ui_control: 프론트엔드 RPA 핸들러 실행 명령 (action, depth, target_label 등)
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="메시지를 입력해 주세요.")
    try:
        return navigate_service.navigate(request)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"네비게이션 에이전트 실행 중 오류가 발생했습니다: {exc}",
        ) from exc
