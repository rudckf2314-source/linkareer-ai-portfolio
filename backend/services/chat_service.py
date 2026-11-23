"""[Business Service Layer] 링커리어 AI 상담 채팅 서비스 (LangChain Agent)."""
import os
import json
from datetime import date
from pathlib import Path
from typing import Optional

# ----- LLM 대화 최종 결과 로컬 Key-Value 캐시 -----
LLM_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "cache" / "llm_cache.json"

class LLMCache:
    def __init__(self):
        self.cache = {}
        self.load()

    def load(self):
        if LLM_CACHE_FILE.is_file():
            try:
                self.cache = json.loads(LLM_CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}

    def save(self):
        try:
            LLM_CACHE_FILE.write_text(
                json.dumps(self.cache, ensure_ascii=False, indent=2), 
                encoding="utf-8"
            )
        except Exception:
            pass

    def get(self, key: str) -> str | None:
        return self.cache.get(key)

    def set(self, key: str, value: str):
        self.cache[key] = value
        self.save()

llm_cache = LLMCache()

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor

from core.config import settings
from core.models import ChatCurrentFilterState, ChatMessage
from core.navigate_models import FilterState
from tools.tavily_tool import tavily_tool
from tools.worknet_tool import worknet_tool
from tools.saramin_tool import saramin_tool, SaraminError
from tools.careernet_tool import careernet_tool


# ----- LangChain 도구 (인프라 Tool 레이어로 위임) -----
@tool
def search_linkareer(query: str) -> str:
    """
    링커리어(linkareer.com)의 채용 정보, 합격 자소서, 인턴/대외활동/면접 후기, 커리어 트렌드를 검색합니다.
    입력은 검색할 핵심 키워드여야 합니다.
    """
    return tavily_tool.search_linkareer_agent(query)


@tool
def search_worknet(keyword: str, search_type: str = "채용정보") -> str:
    """
    고용24(워크넷) Open API로 취업 관련 공공데이터를 검색합니다.
    - search_type: '채용정보'(채용행사+공채속보+공채기업정보 통합), '채용행사', '공채속보', '공채기업정보',
      '직업정보', '직무정보', '강소기업', '학과정보', '훈련과정' 중 1택
    ※ 채용정보목록/상세 API는 별도 승인 필요. 현재는 채용행사·공채속보·공채기업정보만 사용 가능.
    """
    return worknet_tool.execute(keyword, search_type=search_type)


@tool
def search_saramin(keyword: str) -> str:
    """
    사람인(saramin.co.kr)에서 채용공고를 검색합니다.
    Serper(Google Search) 우선, 실패 시 Tavily 폴백으로 saramin.co.kr 공고를 수집합니다.
    입력은 검색할 핵심 키워드(직무, 기업명, 분야 등)입니다.
    """
    try:
        jobs = saramin_tool.execute(keyword)
    except SaraminError as e:
        return f"사람인 검색 오류: {e.message}"
    if not jobs:
        return f"사람인에서 '{keyword}' 관련 채용공고를 찾을 수 없습니다."
    lines = []
    for idx, job in enumerate(jobs[:15], 1):
        lines.append(
            f"[{idx}] [사람인] {job.get('title', '')}\n"
            f"URL: {job.get('link', '')}\n"
            f"요약: {job.get('snippet', '')}\n"
        )
    return "\n".join(lines)


@tool
def search_wanted(keyword: str) -> str:
    """
    원티드(wanted.co.kr)에서 채용공고를 검색합니다.
    Tavily를 통해 wanted.co.kr/wd 채용공고를 수집합니다.
    입력은 검색할 핵심 키워드(직무, 기업명, 분야 등)입니다.
    """
    jobs = tavily_tool._raw_search(f"site:wanted.co.kr/wd {keyword}", max_results=15)
    if not jobs:
        return f"원티드에서 '{keyword}' 관련 채용공고를 찾을 수 없습니다."
    lines = []
    for idx, job in enumerate(jobs, 1):
        lines.append(
            f"[{idx}] [원티드] {job.get('title', '')}\n"
            f"URL: {job.get('url', '')}\n"
            f"요약: {job.get('content', '')}\n"
        )
    return "\n".join(lines)


@tool
def search_careernet(keyword: str, search_type: str = "직업정보") -> str:
    """
    커리어넷(career.go.kr) 진로 공공데이터를 보조적으로 검색합니다.
    - search_type: '직업정보'(하는일·준비방법·탐색법), '학과정보'(전공-진로 연계)
    ※ 고용24·링커리어·사람인 1차 결과가 부족할 때 보완 참고용으로만 사용하세요.
    """
    return careernet_tool.execute(keyword, search_type=search_type)


_BASE_SYSTEM_PROMPT = (
    "당신은 대한민국 대표 취업 플랫폼 '링커리어(Linkareer)'의 공식 취업 비서이자 커리어 전문 어드바이저인 '링커리어 AI 에이전트'입니다.\n\n"
    "당신의 주요 임무는 다음과 같습니다:\n"
    "1. 일반 취업 질문 답변: 대외활동, 공모전, 인턴십, 채용 트렌드 질문에 대해 `search_linkareer` 도구로 검색하여 답변합니다.\n"
    "2. 맞춤형 커리어 분석 및 대외활동 추천 (핵심 기능):\n"
    "   - 사용자의 현재 스펙 요약과 직업흥미/성격 심리검사 결과를 바탕으로 직무 전문성 및 진정성을 분석합니다.\n"
    "   - [분석 단계]\n"
    "     a) 역량 진단: 지원하는 직무/산업군에 부합하는 기준과 비교하여 현재 스펙의 강점과 보완이 필요한 영역(기술 스택 공백, 실무 경험 부족 등)을 진단합니다.\n"
    "     b) 역량 공백 도출: 목표 직무에 합격하기 위해 보완해야 할 구체적인 스킬이나 경험을 도출합니다.\n"
    "     c) 맞춤형 추천 검색: 보완이 필요한 직무 키워드를 바탕으로 `search_linkareer` 등의 도구를 실행하여 최신의 추천 대외활동, 공모전, 혹은 롤모델이 될 수 있는 합격 사례를 검색합니다.\n"
    "     d) 최종 피드백 구성: 진단 결과(강점/보완점)와 함께 실시간 검색된 대외활동 및 합격 사례의 실제 URL 링크(Markdown 형식)를 매칭하여 실질적인 빌드업 방향을 제안하십시오.\n\n"
    "[에이전트 행동 지침]\n"
    "1. 검색 쿼리 작성 및 도구 선택: 사용자가 묻는 질문이나 역량 진단 결과에 맞게 키워드를 도출하고, `search_linkareer`, `search_worknet`, `search_saramin` 도구를 적절히 실행하십시오. **모집 공고나 정규직 채용, 기업의 세부 직무 정보를 탐색할 때는 워크넷·사람인 도구를 상호보완으로 활용하십시오.**\n"
    "   - **워크넷 다중 탐색 가이드**: `search_worknet` 도구 호출 시 `search_type`을 변경하여 다양한 공공 데이터를 얻으세요.\n"
    "     * 채용정보: 채용행사+공채속보+공채기업정보 통합 검색 (채용정보목록 API는 미승인)\n"
    "     * 채용행사/공채속보/공채기업정보: 개별 검색\n"
    "     * 직업정보: 해당 직업의 연봉, 향후 전망, 하는 일 상세 탐색\n"
    "     * 직무정보: (NCS기반) 해당 직무의 요구 KSA(지식/기술/태도) 파악하여 자소서 진단 기준으로 활용\n"
    "     * 강소기업/학과정보/훈련과정: 별도 API 승인 필요 — 미연동 시 채용정보·공채속보로 대체\n"
    "   - **사람인 채용공고 탐색 가이드**: `search_saramin` 도구로 saramin.co.kr의 정규직·신입·경력·인턴 채용공고를 검색하십시오. 기업명+직무, 분야+직무 등 키워드로 호출하고, 링커리어·워크넷 결과와 교차 검증하여 풀을 넓히십시오.\n"
    "   - **커리어넷 보조 참고 가이드**: `search_careernet`은 **보조 전용**입니다. 1차로 `search_worknet`·`search_linkareer`·`search_saramin`을 충분히 사용한 뒤, 전공-직무 연계(`search_type='학과정보'`)나 진로 맥락(`search_type='직업정보'`: 하는일·준비방법)이 부족할 때만 호출하십시오. 채용공고·합격자소서의 주 출처로 사용하지 마십시오.\n"
    "   - **기업분석 탐색 가이드**: 사용자가 특정 기업의 분석 자료(예: '[선택된 기업] 기업분석')를 요구할 경우, `search_linkareer` 도구의 쿼리에 '기업분석' 키워드를 반드시 포함하여 실행하십시오. "
    "기업명은 반드시 [현재 UI 필터 상태]의 선택된 기업 또는 사용자가 이번 발화에서 직접 언급한 기업만 사용하십시오. (예: `query=\"[선택된 기업] 기업분석\"`)\n"
    "   - **키워드(산업군/직무) 매칭 확장**: 사용자가 요구한 특정 키워드(예: '금융', 'IT' 등)가 활동의 **제목에 없더라도, 본문 요약이나 '주최기관(기업명)' 정보에 해당 키워드나 관련 기업명이 포함되어 있다면 적합한 활동으로 인정**하고 추천에 적극 포함하십시오.\n"
    "2. 신뢰성 및 근거 제시: 답변하는 모든 내용은 검색 결과의 텍스트에 기반해야 하며, 임의로 정보를 지어내거나 추정하지 마십시오. 검색 결과에 없는 사실은 모른다고 정직하게 밝히십시오.\n"
    "3. 출처 URL 명기 (필수): 답변에서 특정 활동, 자소서, 팁 등을 소개할 때, 매칭되는 검색 결과의 실제 URL을 반드시 함께 적절한 텍스트 링크 형식(Markdown)으로 표기하여 사용자가 클릭하여 직접 링커리어 사이트에서 원문을 읽을 수 있도록 하십시오. "
    "(예: '[[선택된 기업] 합격 자소서 보기](https://linkareer.com/...)')\n"
    "4. 카테고리 명확한 식별 및 분류 (최우선 이름 기반 식별 규칙):\n"
    "   당신은 검색 결과에 나타나는 활동들을 활동 이름(명칭)에 포함된 키워드를 기준으로 다음 세 가지 범주로 명확히 판별해야 합니다.\n"
    "   - **[주의사항]**: 검색 결과 제목 끝에 공통으로 붙는 ' | 공모전 대외활동' 같은 SEO용 접미사는 완벽히 무시하고, **실제 핵심 활동명 본문**(예: 'Software Engineer Intern')만을 기준으로 판별하십시오.\n"
    "   - **공모전(Contest)**: 실제 활동 이름에 '챌린지', '공모전', '대회' 중 하나라도 **반드시** 명시되어 있어야만 합니다. 이 3가지 키워드 중 하나라도 없으면 절대 공모전으로 분류할 수 없습니다.\n"
    "   - **대외활동(Extracurricular Activity)**: 실제 활동 이름에 '대외활동', '기자단', '홍보대사', '동아리' 중 하나라도 **반드시** 명시되어 있어야만 합니다.\n"
    "   - **모집 공고(Recruitment)**: 본문 내용 요약에 **'채용형태'**라는 단어가 포함되어 있거나, 실제 활동 이름에 '아카데미', '교육', '서포터즈', '인턴', '채용', '부트캠프'가 명시되어 있거나, '1기', '2기' 처럼 '~기'로 기수가 명시되어 있는 경우입니다.\n"
    "   - **태깅 규칙**: 답변에 등장하는 모든 활동 항목의 제목 맨 앞에는 **반드시 `[공모전]`, `[대외활동]`, `[모집 공고]` 중 하나로 태그를 표기**하십시오.\n"
    "   - **[절대 규칙 - 억지 추천 금지]**: 만약 검색된 결과 중에 사용자가 요청한 범주(예: 순수 공모전)에 부합하는 항목이 **단 1개도 없다면**, 절대 비슷한 다른 항목(모집 공고 등)을 해당 범주인 척 속이거나 임의로 태그를 붙여서 추천하지 마십시오. 반드시 추천 목록 작성을 강제 중단하고 '현재 검색 결과 중 조건에 맞는 [요청 범주명] 항목이 없습니다'라고만 단호하고 명확하게 답변하십시오.\n"
    "   - **엄격한 필터링**: 사용자가 특정 유형만 탐색하도록 필터 옵션을 명시한 경우, 해당 조건에 맞지 않는 항목은 수집/가공 결과에서 철저하게 제외(Filtering)하고 부합하는 데이터만 선별하여 답변을 작성하십시오.\n"
    "5. 진행 중인 마감 예정 활동 필터링 및 표기 규칙 (최우선 마감 규칙):\n"
    "   - 공모전, 대외활동, 채용 등을 소개할 때는 **이미 마감되었거나 지난 활동은 절대 제외**하십시오.\n"
    "   - 반드시 현재 지원 가능하고 마감 기한이 아직 남은 실시간 진행 중인 활동만 제공해야 합니다.\n"
    "   - 각 활동의 마감일은 연월일 날짜 형태 대신, **반드시 마감까지 남은 일수를 나타내는 'D-' 형식(예: D-5, D-12, D-DAY, D-2 등)으로만 표시**해 주십시오.\n"
    "   - **[가장 중요한 규칙]**: 링커리어 사이트의 최신 정보를 파싱 및 크롤링할 때 마감 카운트다운이 **'D+'로 기재된 항목(예: D+5, D+12 등)은 서치하는 날을 기준으로 이미 마감기한이 지난 활동**을 의미하므로 **무조건 철저하게 제외**해야 합니다. 오직 마감일이 아직 도래하지 않은 'D-' 항목만 선별하십시오.\n"
    "6. 출력 개수 보장: 검색된 추천 항목이 존재한다면, 임의로 2~3개만 요약하지 말고 **검색된 모든 유효 항목(최대 10개)을 전부 사용자에게 제공**하여 선택의 폭을 넓혀주십시오.\n"
    "7. 답변 스타일: 한국어로 매우 친절하고 전문적이며 구조적인 어조(다나까/해요체 혼용)로 답변해 주십시오. 핵심 내용은 불릿 포인트나 볼드체 등을 활용하여 가독성 있게 정리하십시오."
)


def _format_filter_context(filter_state: FilterState) -> str:
    lines = [
        "[현재 UI 필터 상태 — 최우선 기준]",
        f"- 기준일: {date.today().isoformat()}",
        f"- 탐색 깊이: {filter_state.depth} (0=초기, 1=분야, 2=직무, 3=기업)",
        f"- 선택된 분야: {filter_state.field or '(미선택)'}",
        f"- 선택된 직무: {filter_state.job or '(미선택)'}",
        f"- 선택된 기업: {filter_state.company or '(미선택)'}",
    ]
    if filter_state.jobs:
        job_names = [
            (j.get("name") or j.get("title") or "") if isinstance(j, dict) else str(j)
            for j in filter_state.jobs[:30]
        ]
        lines.append(f"- 화면 직무 목록 (step2): {', '.join(job_names)}")
    if filter_state.companies:
        comp_names = [
            (c.get("name") or c.get("title") or "") if isinstance(c, dict) else str(c)
            for c in filter_state.companies[:30]
        ]
        lines.append(f"- 화면 기업 목록 (step3): {', '.join(comp_names)}")
    return "\n".join(lines)


def _build_chat_system_prompt(
    filter_state: FilterState,
    user_spec_summary: Optional[str],
    psychological_test_summary: Optional[str],
) -> str:
    filter_rules = (
        "\n\n[UI 필터 동기화 — 절대 규칙]\n"
        "1. 위 [현재 UI 필터 상태]를 모든 답변의 최우선 기준으로 삼으십시오.\n"
        "2. 선택된 기업이 '(미선택)'이면 특정 기업명을 지레짐작하여 답변·검색 쿼리에 넣지 마십시오. "
        "사용자가 이번 발화에서 직접 언급한 경우에만 해당 기업을 사용하십시오.\n"
        "3. 선택된 분야·직무가 있으면 그 맥락에 맞춰 답하십시오. 필터와 무관한 범용 취업 로드맵"
        "(프로그래밍 언어 → 자료구조 → HTTP → DB → 프레임워크 단계 나열 등)을 출력하지 마십시오.\n"
        "4. 대화 히스토리, 사용자 스펙, 심리검사 결과를 유지하며 이전에 논의한 맥락을 잃지 마십시오.\n"
        "5. 사용자가 직무·분야 변경 의사를 밝히면 기존 기업 맥락에 갇혀 딱딱하게 거절하지 말고, "
        "새 직무/분야 기준으로 유연하게 안내하십시오.\n"
    )

    spec_context = f"\n\n[사용자 스펙 요약]\n{user_spec_summary}" if user_spec_summary else ""
    psych_context = (
        f"\n\n[직업·심리검사 결과]\n{psychological_test_summary}"
        if psychological_test_summary
        else ""
    )

    return (
        _BASE_SYSTEM_PROMPT
        + "\n\n"
        + _format_filter_context(filter_state)
        + filter_rules
        + spec_context
        + psych_context
    )


class ChatService:
    """LangChain Tool-Calling Agent를 캡슐화한 상담 서비스."""

    def __init__(self) -> None:
        self._tools = [search_linkareer, search_worknet, search_saramin, search_wanted, search_careernet]
        self._llm = ChatOpenAI(
            model=settings.OPENAI_MODEL, temperature=0.3, openai_api_key=settings.OPENAI_API_KEY,
        )

    @staticmethod
    def _build_history(messages: list[ChatMessage]) -> list:
        history = []
        for msg in messages[-20:]:
            if msg.role == "human":
                history.append(HumanMessage(content=msg.content))
            elif msg.role == "ai":
                history.append(AIMessage(content=msg.content))
        return history

    @staticmethod
    def _to_filter_state(state: ChatCurrentFilterState | FilterState | None) -> FilterState:
        if state is None:
            return FilterState()
        if isinstance(state, FilterState):
            return state
        return FilterState(**state.model_dump())

    def chat(
        self,
        message: str,
        chat_history: list[ChatMessage],
        current_filter_state: ChatCurrentFilterState | FilterState | None = None,
        user_spec_summary: Optional[str] = None,
        psychological_test_summary: Optional[str] = None,
    ) -> str:
        import re

        filter_state = self._to_filter_state(current_filter_state)

        # 1. 희망 직무 탐색 2·3단계용 프롬프트 감지 → 캐시 키 (분야→직무→기업)
        cache_key = None
        if "채용·성장 가능성이 높은 직무" in message or '"jobs"' in message:
            field = filter_state.field or ""
            if not field:
                m = re.search(r"'(.*?)'\s*분야에서", message)
                if m:
                    field = m.group(1).strip()
            if field:
                cache_key = f"llm_roadmap_jobs_{field}"

        elif "직무를 채용·모집하는 국내 기업" in message or '"companies"' in message:
            field = filter_state.field or ""
            job = filter_state.job or ""
            if not field:
                m_field = re.search(r"'(.*?)'\s*분야에서", message)
                if m_field:
                    field = m_field.group(1).strip()
            if not job:
                m_job = re.search(r"\*\*'(.*?)'\*\*\s*직무를", message)
                if not m_job:
                    m_job = re.search(r"'(.*?)'\s*직무를\s*채용", message)
                if m_job:
                    job = m_job.group(1).strip()
            if field and job:
                cache_key = f"llm_roadmap_companies_{field}_{job}"

        # 2. 로컬 Key-Value 캐시 조회 및 즉시 반환 (수 밀리초 이내 완료)
        if cache_key:
            cached_val = llm_cache.get(cache_key)
            if cached_val:
                return cached_val

        system_prompt = _build_chat_system_prompt(
            filter_state,
            user_spec_summary,
            psychological_test_summary,
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        agent = create_tool_calling_agent(self._llm, self._tools, prompt)
        executor = AgentExecutor(
            agent=agent, tools=self._tools, verbose=True, handle_parsing_errors=True,
        )
        result = executor.invoke({
            "input": message,
            "chat_history": self._build_history(chat_history),
        })
        answer = result["output"]

        # 3. 새로운 결과 로컬 Key-Value 캐싱 — 오류 응답 캐싱 차단
        _ERROR_SIGNALS = (
            "파싱하지 못했습니다",
            "결과에서 직접 확인하세요",
            "찾을 수 없습니다",
            "오류가 발생",
            "실패했습니다",
            "알 수 없습니다",
        )
        if cache_key and answer and not any(sig in answer for sig in _ERROR_SIGNALS):
            # 직무/기업 목록 응답은 최소 2개 이상 항목이 있을 때만 캐싱
            if "jobs" in cache_key or "companies" in cache_key:
                if len(answer.strip()) >= 100:
                    llm_cache.set(cache_key, answer)
            else:
                llm_cache.set(cache_key, answer)

        return answer


# 싱글톤 인스턴스
chat_service = ChatService()
