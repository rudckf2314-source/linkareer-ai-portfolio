"""[Controller Layer] AI 상담 채팅 라우터."""
from fastapi import APIRouter, HTTPException

from core.models import ChatRequest, ChatResponse
from services.chat_service import chat_service

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """링커리어 AI 에이전트와 대화 (chat_history 지원)."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="질문 메시지를 입력해 주세요.")
    try:
        answer = chat_service.chat(
            request.message,
            request.chat_history,
            current_filter_state=request.current_filter_state,
            user_spec_summary=request.user_spec_summary,
            psychological_test_summary=request.psychological_test_summary,
        )
        return ChatResponse(response=answer)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"에이전트 실행 중 오류가 발생했습니다: {str(e)}")
