"""
[Business Service Layer] AI Agent형 UI 자동 제어(RPA) 네비게이션 서비스.

OpenAI Function Calling(Tools) API를 사용해:
  1) 유저 의도를 분석하고
  2) 대화 응답(reply)과 UI 조작 명령(ui_control)을 동시에 정형 출력합니다.

4개 Tool 구조:
  - set_field_filter     : 분야(대분류) 신규 선택 → 직무 탐색 실행
  - set_job_filter       : 직무(중분류) pick-btn 클릭 → 기업 탐색 실행
  - set_company_filter   : 기업(소분류) pick-btn 클릭
  - find_companies_by_job: 직무 기준 기업 재탐색 — 동일 직무를 채용하는 대안 기업 동적 스왑

설계 원칙:
- 특정 분야/직무/기업명을 코드에 하드코딩하지 않음 (모두 LLM 동적 추출)
- depth 추상화: 1=분야, 2=직무, 3=기업
- tool call이 없는 경우 → action="none" (일반 커리어 상담 대화)
"""
import json
import logging
from datetime import date
from typing import Optional

from openai import OpenAI

from core.config import settings
from core.models import ChatMessage
from core.navigate_models import (
    FilterState,
    NavigateRequest,
    NavigateResponse,
    UiControlAction,
    UiControlCommand,
)

logger = logging.getLogger(__name__)


# ============================================================
# Function Calling Tools 정의 (4개)
# ============================================================
_NAVIGATE_TOOLS = [
    # ── Tool 1: 분야(대분류) 신규 선택 ──
    {
        "type": "function",
        "function": {
            "name": "set_field_filter",
            "description": (
                "사용자가 처음으로 탐색할 산업·직무 분야(대분류)를 언급했을 때만 호출합니다. "
                "호출 시 프론트엔드 '희망 직무 탐색' 탭에서 해당 분야의 **직무 목록** 탐색이 자동 실행됩니다. "
                "주의: 이미 직무가 선택된 상태에서 '이 직무 채용하는 다른 기업 찾아줘' 같은 요청은 "
                "이 Tool이 아닌 find_companies_by_job 을 호출해야 합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "field_label": {
                        "type": "string",
                        "description": "탐색할 분야명 (예: [분야명]). 사용자 발화에서 추출.",
                    },
                    "reply": {
                        "type": "string",
                        "description": "분야 선택을 확인하고 직무 탐색 시작을 안내하는 친절한 한국어 응답.",
                    },
                    "next_depth_hint": {
                        "type": "string",
                        "description": "다음 단계 안내 힌트. 선택적.",
                    },
                },
                "required": ["field_label", "reply"],
            },
        },
    },

    # ── Tool 2: 직무(중분류) 선택 ──
    {
        "type": "function",
        "function": {
            "name": "set_job_filter",
            "description": (
                "사용자가 특정 직무(중분류)를 언급하거나 선택 의사를 밝혔을 때 호출합니다. "
                "현재 step2 pick-btn 목록에서 해당 직무를 자동 클릭하면, "
                "프론트엔드가 해당 직무를 채용하는 기업 목록(step3) 탐색을 실행합니다. "
                "반드시 현재 FilterState의 jobs 목록에 실제로 존재하는 직무명만 사용하세요. "
                "목록에 없는 직무를 원하면 이 Tool 대신 find_companies_by_job 을 호출하세요."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_label": {
                        "type": "string",
                        "description": "선택할 직무명. FilterState.jobs 목록의 실제 값과 일치해야 합니다.",
                    },
                    "reply": {
                        "type": "string",
                        "description": "직무 선택 확인 및 기업 탐색 안내 한국어 응답.",
                    },
                    "next_depth_hint": {
                        "type": "string",
                        "description": "다음 단계 안내 힌트. 선택적.",
                    },
                },
                "required": ["job_label", "reply"],
            },
        },
    },

    # ── Tool 3: 기업(소분류) 선택 ──
    {
        "type": "function",
        "function": {
            "name": "set_company_filter",
            "description": (
                "사용자가 특정 기업(소분류)을 언급하거나 선택 의사를 밝혔을 때 호출합니다. "
                "현재 step3 pick-btn 목록에서 해당 기업을 자동 클릭합니다. "
                "반드시 현재 FilterState의 companies 목록에 실제로 존재하는 기업명만 사용하세요. "
                "목록에 없는 기업을 원하면 find_companies_by_job 으로 동일 직무의 다른 기업을 재탐색하세요."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company_label": {
                        "type": "string",
                        "description": "선택할 기업명. FilterState.companies 목록의 실제 값과 정확히 일치해야 합니다.",
                    },
                    "reply": {
                        "type": "string",
                        "description": "기업 선택 완료 및 다음 단계(벤치마킹·로드맵) 안내 한국어 응답.",
                    },
                    "next_depth_hint": {
                        "type": "string",
                        "description": "다음 단계 안내 힌트. 선택적.",
                    },
                },
                "required": ["company_label", "reply"],
            },
        },
    },

    # ── Tool 4: 직무 기준 기업 재탐색 ──
    {
        "type": "function",
        "function": {
            "name": "find_companies_by_job",
            "description": (
                "사용자가 원하는 직무가 현재 jobs 목록에 없거나, "
                "해당 직무를 채용하는 다른·추가 기업을 찾아달라고 요청할 때 호출합니다.\n"
                "트리거 발화 예시:\n"
                "  - '백엔드 개발자 채용하는 기업 찾아줘'\n"
                "  - '이 직무 말고 다른 기업 없나?'\n"
                "  - '카카오 말고 토스 같은 곳도 알려줘'\n"
                "  - '다시 검색해줘', '재탐색해줘'\n"
                "호출 시 동작: 프론트엔드가 desired_job 기준으로 기업 탐색(selectRoadmapJob)을 실행합니다. "
                "jobs 목록이 비어 있으면 분야 기준 직무 탐색 후 desired_job을 자동 선택 시도합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "search_query": {
                        "type": "string",
                        "description": (
                            "분야·직무 조합 검색 쿼리. "
                            "현재 분야와 원하는 직무를 조합해서 만드세요. "
                            "예: 현재 분야='IT', 원하는 직무='백엔드 개발자' → 'IT 백엔드 개발자'. "
                        ),
                    },
                    "desired_job": {
                        "type": "string",
                        "description": (
                            "사용자가 원하는 직무명 (원본 그대로). "
                            "예: '백엔드 개발자', '데이터 사이언티스트'. "
                            "기업 탐색(selectRoadmapJob)의 기준 직무로 사용됩니다."
                        ),
                    },
                    "reply": {
                        "type": "string",
                        "description": (
                            "재탐색 시작을 알리는 응답. "
                            "예: '백엔드 개발자를 채용하는 기업들을 새로 탐색해드릴게요! 잠시 기다려주세요.'"
                        ),
                    },
                },
                "required": ["search_query", "desired_job", "reply"],
            },
        },
    },
]


def _build_system_prompt(
    filter_state: FilterState,
    user_spec_summary: Optional[str],
    psychological_test_summary: Optional[str] = None,
) -> str:
    """현재 UI 필터 상태와 유저 스펙을 컨텍스트로 주입한 시스템 프롬프트를 생성합니다."""

    # 현재 필터 상태 텍스트
    state_lines = ["[현재 UI 필터 상태 — 최우선 기준]"]
    state_lines.append(f"- 기준일: {date.today().isoformat()}")
    state_lines.append(f"- 탐색 깊이: {filter_state.depth} (0=초기, 1=분야, 2=직무, 3=기업)")
    state_lines.append(f"- 선택된 분야: {filter_state.field or '(미선택)'}")
    state_lines.append(f"- 선택된 직무: {filter_state.job or '(미선택)'}")
    state_lines.append(f"- 선택된 기업: {filter_state.company or '(미선택)'}")

    if filter_state.jobs:
        job_names = [
            (j.get("name") or j.get("title") or "") if isinstance(j, dict) else str(j)
            for j in filter_state.jobs[:30]
        ]
        jobs_text = ", ".join(job_names)
        state_lines.append(f"- 현재 화면의 직무 목록 (step2): {jobs_text}")
    else:
        state_lines.append("- 현재 화면의 직무 목록: (탐색 안 됨)")

    if filter_state.companies:
        comp_names = [
            (c.get("name") or c.get("title") or "") if isinstance(c, dict) else str(c)
            for c in filter_state.companies[:30]
        ]
        companies_text = ", ".join(comp_names)
        state_lines.append(f"- 현재 화면의 기업 목록 (step3): {companies_text}")
    else:
        state_lines.append("- 현재 화면의 기업 목록: (탐색 안 됨)")

    filter_context = "\n".join(state_lines)

    spec_context = ""
    if user_spec_summary:
        spec_context = f"\n\n[사용자 스펙 요약]\n{user_spec_summary}"

    psych_context = ""
    if psychological_test_summary:
        psych_context = f"\n\n[직업·심리검사 결과]\n{psychological_test_summary}"

    return (
        "당신은 링커리어(Linkareer) 플랫폼의 맞춤형 커리어 챗봇입니다.\n"
        "사용자의 말을 분석해 적절한 Function Tool을 호출하거나, 일반 커리어 상담을 진행합니다.\n\n"

        "━━━ Tool 선택 결정 트리 (위에서부터 순서대로 판단) ━━━\n\n"

        "【STEP 1】 직무 기준 기업 재탐색 → find_companies_by_job\n"
        "  아래 조건 중 하나라도 해당하면 즉시 find_companies_by_job 호출:\n"
        "  ① 현재 직무 목록(jobs)에 없는 직무를 사용자가 원하면서 기업 탐색을 요청하는 발화\n"
        "     예: '백엔드 개발자 채용하는 기업 찾아줘', '풀스택 개발자가 하고 싶어', '다른 기업 없나?',\n"
        "         '재탐색해줘', '다시 검색해줘', '[원하는 직무] 채용하는 곳 알려줘'\n"
        "  ② 현재 기업 목록(companies)에 없는 기업을 원하지만 동일 직무 맥락을 유지해야 하는 상황\n"
        "  ③ 사용자가 직무 중심으로 대안 기업·스왑을 원하는 상황 (기업 lock-in 방지)\n"
        "  → search_query: '현재 분야 + 원하는 직무' 조합 (예: 'IT 백엔드 개발자')\n"
        "  → desired_job: 사용자가 원하는 직무명 원본\n"
        "  ※ 특정 기업에 갇혀 '불가능합니다'만 반복하지 말고 반드시 Tool로 재탐색을 제안·실행\n\n"

        "【STEP 2】 분야 신규 선택 → set_field_filter\n"
        "  사용자가 처음으로 분야를 명확히 언급하고, 직무 기준 재탐색이 아닌 경우\n\n"

        "【STEP 3】 직무 선택 → set_job_filter\n"
        "  사용자가 직무를 언급 + jobs 목록(step2)에 실제로 존재하는 경우\n"
        "  ※ jobs 목록에 없는 직무 → find_companies_by_job 으로 유도\n\n"

        "【STEP 4】 기업 선택 → set_company_filter\n"
        "  사용자가 기업을 언급 + companies 목록(step3)에 실제로 존재하는 경우\n"
        "  ※ companies 목록에 없는 기업 → find_companies_by_job 으로 동일 직무의 대안 기업 재탐색\n"
        "  ※ 선택된 기업이 '(미선택)'이면 특정 기업명을 임의로 고정하지 마라\n\n"

        "【STEP 5】 일반 커리어 상담\n"
        "  위 어디에도 해당 안 되면 Tool 없이 텍스트만 응답\n"
        "  ※ 범용 취업 로드맵(프로그래밍 언어→자료구조→HTTP→DB→프레임워크 단계 나열) 절대 금지\n"
        "  ※ [현재 UI 필터 상태]와 사용자 스펙·심리검사·대화 히스토리에 맞춰 구체적으로 답변\n\n"

        "━━━ 절대 규칙 ━━━\n"
        "✗ 선택된 기업이 '(미선택)'인데 특정 기업명(예: 임의의 IT 기업)을 답변에 노출·고정 → 금지\n"
        "✗ 현재 직무 목록에 없는 직무인데 set_job_filter 호출 → 금지\n"
        "✗ 현재 기업 목록에 없는 기업인데 set_company_filter 호출 → 금지\n"
        "✗ 직무 기준 재탐색·대안 기업 요청인데 텍스트로만 '다른 기업에서 찾아보겠습니다' → 금지 (반드시 Tool 호출)\n"
        "✗ 특정 기업/직무/분야를 LLM이 임의로 지어내어 하드코딩 → 금지\n"
        "✗ 대화 중 사용자 스펙·심리검사·이전 필터 맥락을 무시한 범용 답변 → 금지\n"
        "✓ target_label / desired_job은 반드시 사용자 발화 또는 현재 목록에서 동적 추출\n"
        "✓ [현재 UI 필터 상태]를 최우선으로 존중\n"
        "✓ 응답은 항상 한국어, 친절하고 간결하게\n\n"

        f"{filter_context}"
        f"{spec_context}"
        f"{psych_context}"
    )


def _build_openai_messages(
    system_prompt: str,
    message: str,
    chat_history: list[ChatMessage],
) -> list[dict]:
    """OpenAI API 형식의 messages 리스트를 생성합니다."""
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for msg in chat_history[-20:]:
        role = "user" if msg.role == "human" else "assistant"
        messages.append({"role": role, "content": msg.content})
    messages.append({"role": "user", "content": message})
    return messages


def _tool_call_to_ui_control(tool_name: str, tool_args: dict) -> UiControlCommand:
    """Function Calling 결과를 UiControlCommand 로 변환합니다."""
    if tool_name == "set_field_filter":
        return UiControlCommand(
            action=UiControlAction.SET_FIELD,
            depth=1,
            target_label=tool_args.get("field_label", ""),
            next_depth_hint=tool_args.get("next_depth_hint"),
            navigate_to_tab=True,
        )
    elif tool_name == "set_job_filter":
        return UiControlCommand(
            action=UiControlAction.SET_JOB,
            depth=2,
            target_label=tool_args.get("job_label", ""),
            next_depth_hint=tool_args.get("next_depth_hint"),
            navigate_to_tab=True,
        )
    elif tool_name == "set_company_filter":
        return UiControlCommand(
            action=UiControlAction.SET_COMPANY,
            depth=3,
            target_label=tool_args.get("company_label", ""),
            next_depth_hint=tool_args.get("next_depth_hint"),
            navigate_to_tab=True,
        )
    elif tool_name == "find_companies_by_job":
        return UiControlCommand(
            action=UiControlAction.SEARCH_BY_JOB,
            depth=2,
            target_label=tool_args.get("search_query", ""),
            desired_job=tool_args.get("desired_job", ""),
            next_depth_hint=tool_args.get("next_depth_hint"),
            navigate_to_tab=True,
        )
    else:
        return UiControlCommand(action=UiControlAction.NONE)


class NavigateService:
    """
    OpenAI Function Calling 기반 AI 네비게이션 서비스.
    사용자 의도 분석 → 대화 응답 + UI 조작 명령 동시 반환.
    """

    def __init__(self) -> None:
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.OPENAI_MODEL

    def navigate(self, request: NavigateRequest) -> NavigateResponse:
        """사용자 메시지를 분석해 reply + ui_control 을 반환합니다."""
        system_prompt = _build_system_prompt(
            request.current_filter_state,
            request.user_spec_summary,
            request.psychological_test_summary,
        )
        messages = _build_openai_messages(
            system_prompt,
            request.message,
            request.chat_history,
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=_NAVIGATE_TOOLS,
                tool_choice="auto",
                temperature=0.2,  # 결정론적 Tool 선택을 위해 낮게 설정
            )
        except Exception as exc:
            logger.error("[NavigateService] OpenAI API 호출 실패: %s", exc)
            raise

        choice = response.choices[0]

        # ── Case 1: Tool 호출이 있는 경우 (finish_reason은 신뢰하지 않음) ──
        if choice.message.tool_calls:
            tool_call = choice.message.tool_calls[0]
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            reply = tool_args.get("reply", f"'{tool_name}' 명령을 실행합니다.")
            ui_control = _tool_call_to_ui_control(tool_name, tool_args)

            logger.info(
                "[NavigateService] Tool=%s action=%s target='%s' desired_job='%s'",
                tool_name,
                ui_control.action,
                ui_control.target_label,
                ui_control.desired_job or "-",
            )
            return NavigateResponse(reply=reply, ui_control=ui_control)

        # ── Case 2: 일반 텍스트 응답 ──
        reply_text = choice.message.content or "죄송합니다, 응답을 생성하지 못했습니다."
        logger.info("[NavigateService] 일반 대화 응답 (ui_control=none)")
        return NavigateResponse(
            reply=reply_text,
            ui_control=UiControlCommand(action=UiControlAction.NONE),
        )


# 싱글톤 인스턴스
navigate_service = NavigateService()
