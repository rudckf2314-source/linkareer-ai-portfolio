"""
[Navigate Models] 챗봇 ↔ 희망 직무 탐색 UI 자동 제어(RPA) 시스템 Pydantic 스키마.

설계 원칙:
- target_label 은 LLM이 실시간 대화에서 동적으로 추출한 값만 사용 (하드코딩 금지)
- depth 추상화:  1 = 분야(대분류), 2 = 직무(중분류), 3 = 기업(소분류)
- SEARCH_BY_JOB: 직무 기준 기업 재탐색 — 특정 직무를 채용하는 기업을 동적으로 찾기
"""
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field

from core.models import ChatMessage


# ====================================================
# 1. UI 제어 명령 (챗봇 → 프론트엔드)
# ====================================================
class UiControlAction(str, Enum):
    NONE = "none"                      # 일반 대화 (UI 조작 없음)
    SET_FIELD = "set_field"            # 1단계: 분야(대분류) 입력 및 직무 탐색 실행
    SET_JOB = "set_job"                # 2단계: 직무(중분류) pick-btn 클릭 → 기업 탐색
    SET_COMPANY = "set_company"        # 3단계: 기업(소분류) pick-btn 클릭
    SEARCH_BY_JOB = "search_by_job"   # 직무 기준 기업 재탐색 (동일 직무·대안 기업 스왑)
    RESET = "reset"                    # 전체 초기화


class UiControlCommand(BaseModel):
    """프론트엔드 RPA 핸들러가 소비하는 UI 조작 명령."""
    action: UiControlAction = Field(
        default=UiControlAction.NONE,
        description="수행할 UI 조작 유형",
    )
    depth: int = Field(
        default=0,
        ge=0, le=3,
        description="필터 깊이 (0=없음, 1=분야, 2=직무, 3=기업)",
    )
    target_label: str = Field(
        default="",
        description=(
            "조작 대상 레이블 (동적값; LLM이 대화에서 추출). "
            "search_by_job 시에는 분야·직무 조합 검색 쿼리 (예: 'IT 백엔드 개발자')."
        ),
    )
    desired_job: Optional[str] = Field(
        default=None,
        description=(
            "search_by_job 전용 — 사용자가 원하는 직무명 (예: '백엔드 개발자'). "
            "기업 탐색 시 이 직무를 기준으로 selectRoadmapJob 을 실행합니다."
        ),
    )
    next_depth_hint: Optional[str] = Field(
        default=None,
        description="다음 단계에서 예상되는 선택지 힌트 (선택적)",
    )
    navigate_to_tab: bool = Field(
        default=True,
        description="True 이면 프론트엔드가 희망 직무 탐색 탭으로 자동 전환",
    )


# ====================================================
# 2. 현재 UI 필터 상태 (프론트엔드 → 백엔드)
# ====================================================
class FilterState(BaseModel):
    """프론트엔드가 현재 유지하고 있는 필터 선택 상태."""
    depth: int = Field(
        default=0,
        ge=0, le=3,
        description="현재 선택 깊이 (0=초기, 1=분야선택됨, 2=직무선택됨, 3=기업선택됨)",
    )
    field: str = Field(default="", description="현재 선택된 분야(대분류)")
    job: str = Field(default="", description="현재 선택된 직무(중분류)")
    company: str = Field(default="", description="현재 선택된 기업(소분류)")
    jobs: List[Any] = Field(
        default_factory=list,
        description="step2 pick-btn 에 렌더링된 직무 목록 (동적)",
    )
    companies: List[Any] = Field(
        default_factory=list,
        description="step3 pick-btn 에 렌더링된 기업 목록 (동적)",
    )


# ====================================================
# 3. Navigate API 요청 / 응답 모델
# ====================================================
class NavigateRequest(BaseModel):
    """POST /api/chat/navigate 요청 바디."""
    message: str = Field(..., description="사용자 입력 메시지")
    chat_history: List[ChatMessage] = Field(
        default_factory=list,
        description="이전 대화 히스토리 (최대 20개)",
    )
    current_filter_state: FilterState = Field(
        default_factory=FilterState,
        description="현재 프론트엔드 UI 필터 상태 (양방향 동기화)",
    )
    user_spec_summary: Optional[str] = Field(
        default=None,
        description="사용자 스펙 요약 텍스트 (프론트에서 buildSpecPayload → specPayloadToText 결과)",
    )
    psychological_test_summary: Optional[str] = Field(
        default=None,
        description="직업·심리검사 결과 요약 (Holland 코드 등)",
    )


class NavigateResponse(BaseModel):
    """POST /api/chat/navigate 응답 바디."""
    reply: str = Field(..., description="챗봇이 사용자에게 전달할 대화 응답 텍스트")
    ui_control: UiControlCommand = Field(
        default_factory=UiControlCommand,
        description="프론트엔드 RPA 핸들러가 실행할 UI 조작 명령",
    )
