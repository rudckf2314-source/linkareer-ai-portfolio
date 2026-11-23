from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
import re

# ==========================================
# 1. 어학점수 모델 (Language Score Model)
# ==========================================
class LanguageScore(BaseModel):
    language_type: str = Field(
        ..., 
        description="어학 종류 (예: TOEIC, TOEFL, OPIc, HSK 등)", 
        examples=["TOEIC", "OPIc"]
    )
    score: str = Field(
        ..., 
        description="점수 또는 등급 (예: 950, AL, 6급 등)", 
        examples=["950", "AL"]
    )
    acquisition_date: str = Field(
        ..., 
        description="취득일 (YYYY-MM 형식)", 
        examples=["2025-08"]
    )

    @field_validator("acquisition_date")
    @classmethod
    def validate_acquisition_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError("취득일은 반드시 'YYYY-MM' 형식이어야 합니다.")
        return v


# ==========================================
# 2. 자격증 모델 (Certificate Model)
# ==========================================
class Certificate(BaseModel):
    name: str = Field(
        ..., 
        description="자격증 명칭 (예: 정보처리기사, SQLD 등)", 
        examples=["정보처리기사"]
    )
    issuer: str = Field(
        ..., 
        description="발행 기관 (예: 한국산업인력공단, 한국데이터산업진흥원 등)", 
        examples=["한국산업인력공단"]
    )
    acquisition_date: str = Field(
        ..., 
        description="취득일 (YYYY-MM 형식)", 
        examples=["2025-06"]
    )

    @field_validator("acquisition_date")
    @classmethod
    def validate_acquisition_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError("취득일은 반드시 'YYYY-MM' 형식이어야 합니다.")
        return v


# ==========================================
# 3. 경력사항 모델 (Experience Model)
# ==========================================
class Experience(BaseModel):
    company_name: str = Field(
        ..., 
        description="회사명", 
        examples=["네이버"]
    )
    employment_type: str = Field(
        ..., 
        description="근무형태 (예: 정규직, 계약직, 인턴, 아르바이트 등)", 
        examples=["인턴"]
    )
    start_date: str = Field(
        ..., 
        description="근무 시작월 (YYYY-MM 형식)", 
        examples=["2025-01"]
    )
    end_date: Optional[str] = Field(
        None, 
        description="근무 종료월 (YYYY-MM 형식, 현재 재직 중인 경우 생략 가능 또는 '재직 중' 입력)", 
        examples=["2025-06"]
    )
    role_summary: str = Field(
        ..., 
        description="담당업무 요약 (최대 500자)", 
        max_length=500,
        examples=["FastAPI 기반 웹 백엔드 개발 및 API 성능 최적화"]
    )

    @field_validator("start_date")
    @classmethod
    def validate_start_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError("근무 시작월은 반드시 'YYYY-MM' 형식이어야 합니다.")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_end_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != "재직 중" and not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError("근무 종료월은 반드시 'YYYY-MM' 형식 또는 '재직 중'이어야 합니다.")
        return v


# ==========================================
# 4. 대외활동 모델 (Extracurricular Activity Model)
# ==========================================
class ExtracurricularActivity(BaseModel):
    activity_type: str = Field(
        ..., 
        description="활동 구분 (교내 / 교외)", 
        examples=["교외"]
    )
    organization_or_name: str = Field(
        ..., 
        description="기관 또는 활동명 (예: 링커리어 서포터즈, 대학생 연합 IT동아리 등)", 
        examples=["링커리어 서포터즈 10기"]
    )
    start_date: str = Field(
        ..., 
        description="활동 시작월 (YYYY-MM 형식)", 
        examples=["2024-09"]
    )
    end_date: str = Field(
        ..., 
        description="활동 종료월 (YYYY-MM 형식)", 
        examples=["2024-12"]
    )
    award: Optional[str] = Field(
        None, 
        description="수상이력 (선택형, 예: 최우수 서포터즈상 등)", 
        examples=["최우수상"]
    )
    summary: str = Field(
        ..., 
        description="활동 내용 요약 (최대 500자)", 
        max_length=500,
        examples=["브랜드 마케팅 전략 수립 및 SNS 콘텐츠 카드뉴스 20건 제작"]
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_dates(cls, v: str) -> str:
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError("날짜는 반드시 'YYYY-MM' 형식이어야 합니다.")
        return v


# ==========================================
# 5. 기본정보 모델 (Basic Info Model)
# ==========================================
class GPAInfo(BaseModel):
    score: float = Field(
        ..., 
        description="본인 학점", 
        ge=0.0, 
        examples=[3.8]
    )
    max_score: float = Field(
        ..., 
        description="만점 기준 (예: 4.5, 4.3, 4.0 등)", 
        ge=0.0, 
        examples=[4.5]
    )

    @model_validator(mode="after")
    def validate_gpa_range(self) -> "GPAInfo":
        if self.score > self.max_score:
            raise ValueError(f"본인 학점({self.score})은 만점 기준({self.max_score})을 초과할 수 없습니다.")
        return self


class BasicInfo(BaseModel):
    name: str = Field(
        ..., 
        description="이름", 
        min_length=1, 
        examples=["홍길동"]
    )
    final_education: str = Field(
        ..., 
        description="최종학력 (고등학교졸업 / 전문대재학 / 전문대졸업 / 대학재학 / 대학졸업 / 대학원석사 / 대학원박사 등)", 
        examples=["대학졸업"]
    )
    school_name: str = Field(
        ..., 
        description="학교명", 
        examples=["한국대학교"]
    )
    major: str = Field(
        ..., 
        description="전공명", 
        examples=["컴퓨터공학과"]
    )
    gpa: GPAInfo = Field(
        ..., 
        description="학점 정보 (본인 학점 및 만점 기준)"
    )
    graduation_status: str = Field(
        ..., 
        description="졸업상태 (졸업 / 졸업예정 / 수료 / 중퇴 / 재학 등)", 
        examples=["졸업"]
    )


# ==========================================
# 6. 매칭선호조건 모델 (Matching Preference Model)
# ==========================================
class MatchingPreference(BaseModel):
    desired_job: str = Field(
        ..., 
        description="희망 직무 (예: 백엔드 개발자, 서비스 기획자 등)", 
        examples=["백엔드 개발자"]
    )
    desired_company_type: str = Field(
        ..., 
        description="희망 기업 형태 (예: 대기업, 중견기업, 스타트업, 공기업 등)", 
        examples=["대기업"]
    )
    desired_industry: str = Field(
        ..., 
        description="희망 산업군 (예: IT/플랫폼, 금융, 이커머스 등)", 
        examples=["IT/플랫폼"]
    )


# ==========================================
# 6-1. 워크넷 직업선호도검사(L형) 모델
# ==========================================
class HollandInterest(BaseModel):
    riasec_code: str = Field(..., description='예: "IR" (탐구형+현실형)')
    highest_types: List[str] = Field(default_factory=list, description='예: ["탐구형", "현실형"]')
    raw_scores: dict = Field(default_factory=dict, description='{"R": 55, "I": 62, ...}')


class BigFivePersonality(BaseModel):
    extraversion: int = Field(default=50, description="외향성 T점수")
    agreeableness: int = Field(default=50, description="호감성 T점수")
    conscientiousness: int = Field(default=50, description="성실성 T점수")
    neuroticism: int = Field(default=50, description="정서적 불안정성 T점수")
    openness: int = Field(default=50, description="경험에 대한 개방성 T점수")


class WorknetTestResult(BaseModel):
    test_date: str = Field(default="", description="검사일 YYYY-MM-DD")
    user_age: int = Field(default=0)
    stated_desired_jobs: List[str] = Field(default_factory=list)
    interest: HollandInterest
    personality: BigFivePersonality


# ==========================================
# 7. 전체 통합 스펙 스키마 (Unified Spec Schema)
# ==========================================
class UserSpecSchema(BaseModel):
    basic_info: BasicInfo = Field(
        ..., 
        description="기본 정보"
    )
    languages: List[LanguageScore] = Field(
        default=[], 
        description="어학 점수 리스트 (동적 추가 가능)"
    )
    certificates: List[Certificate] = Field(
        default=[], 
        description="자격증 리스트 (동적 추가 가능)"
    )
    careers: List[Experience] = Field(
        default=[], 
        description="경력 사항 리스트 (동적 추가 가능)"
    )
    activities: List[ExtracurricularActivity] = Field(
        default=[], 
        description="대외 활동 리스트 (동적 추가 가능)"
    )
    matching_preference: MatchingPreference = Field(
        ..., 
        description="매칭 선호 조건"
    )
    psychological_test: Optional[WorknetTestResult] = Field(
        default=None,
        description="워크넷 직업선호도검사(L형) 구조화 결과 (선택)",
    )

    @model_validator(mode="after")
    def segment_languages_and_certificates(self) -> "UserSpecSchema":
        """어학 키워드가 자격증 칸에 들어온 경우 languages로 강제 라우팅."""
        from core.spec_classifier import sanitize_user_spec_dicts

        lang_dicts, cert_dicts = sanitize_user_spec_dicts(
            [l.model_dump() for l in self.languages],
            [c.model_dump() for c in self.certificates],
        )
        self.languages = [LanguageScore(**x) for x in lang_dicts]
        self.certificates = [Certificate(**x) for x in cert_dicts]
        return self


# ==========================================
# 8. 채팅 / 검색 API 입출력 모델
# ==========================================
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCurrentFilterState(BaseModel):
    """챗봇 API용 UI 필터 상태 (프론트 filterState / roadmap 동기화)."""
    depth: int = Field(default=0, ge=0, le=3)
    field: str = Field(default="", description="현재 선택된 분야")
    company: str = Field(default="", description="현재 선택된 기업 (미선택 시 빈 문자열)")
    job: str = Field(default="", description="현재 선택된 직무")
    companies: List[Any] = Field(default_factory=list)
    jobs: List[Any] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    chat_history: List["ChatMessage"] = []
    current_filter_state: ChatCurrentFilterState = Field(default_factory=ChatCurrentFilterState)
    user_spec_summary: Optional[str] = None
    psychological_test_summary: Optional[str] = None


class ChatResponse(BaseModel):
    response: str


class KeywordSuggestionItem(BaseModel):
    text: str
    source: str


class KeywordSuggestResponse(BaseModel):
    query: str
    context: str
    suggestions: List[KeywordSuggestionItem]


class CompanyAnalysisMatchRequest(BaseModel):
    target_field: str = ""
    target_company: str
    target_job: str = ""


class CorporateAnalysisContent(BaseModel):
    has_data: bool = False
    company_full_name: str = ""
    archive_title: str = ""
    key_features: List[str] = Field(default_factory=list)
    target_viewer_url: str = ""
    is_latest: bool = False
    match_type: str = "none"
    company_match_score: float = 0
    period_label: str = ""


class CompanyAnalysisSuggestResponse(BaseModel):
    query: str = ""
    suggestions: List[str] = Field(default_factory=list)


class CompanyAnalysisMatchResponse(BaseModel):
    search_context: dict = Field(default_factory=dict)
    corporate_analysis_content: CorporateAnalysisContent
    related_searches: List[str] = Field(default_factory=list)


# ==========================================
# 9. 멀티 에이전트(CrewAI) HITL 입출력 모델
# ==========================================
# --- HITL 단계별 요청용 스키마 (무상태: 직전 단계 확정 데이터를 다시 주입) ---
class RoadmapCriteriaRequest(BaseModel):
    """[HITL 1단계] 합격 기준 모델 생성 요청."""
    user_spec: UserSpecSchema
    target_field: str
    target_company: str
    target_job: str
    psychological_test: Optional[dict] = None  # WorknetTestResult JSON 스냅샷
    hope_career_context: Optional[dict] = None  # hopeCareer_cash 스냅샷


class RoadmapGapRequest(RoadmapCriteriaRequest):
    """[HITL 2단계] 1단계 목표(벤치마크) 스펙 + 1차 유저 피드백으로 갭 진단 요청."""
    benchmark_output: Optional[dict] = None
    user_feedback_1: Optional[str] = None  # HITL 1차 유저 피드백


class RoadmapFinalRequest(RoadmapGapRequest):
    """[최종 3단계] 2단계 확정 갭 + 2차 유저 피드백으로 최종 로드맵 요청."""
    confirmed_gap: dict
    user_feedback_2: Optional[str] = None  # HITL 2차 유저 피드백


# --- 최종 결과 리포트 반환용 스키마 ---
class GapItem(BaseModel):
    category: str = Field(..., description="'진정성(Authenticity)' 또는 '전문성(Professionalism)' 중 하나")
    required_criteria: str = Field(..., description="합격스펙에서 요구한 기준 역량")
    current_status: str = Field(..., description="사용자의 현재 상태 및 부족 사유")
    gap_description: str = Field(..., description="공백의 상세 정성 분석 피드백")
    severity_score: int = Field(..., description="부족도 점수 (1-100)")


class SourcedActivity(BaseModel):
    source_platform: str = Field(..., description="'링커리어(Tavily)' 또는 '고용24(Work24)' 또는 '사람인'")
    title: str = Field(..., description="공모전, 대외활동, 자격증, 공채공고 명칭")
    link_url: Optional[str] = Field(None, description="상세보기 바로가기 URL")
    keyword_match: str = Field(..., description="어떠한 Gap을 메우기 위해 추천되었는지 매칭 속성")
    d_day_label: str = Field(default="", description="D-Day 라벨 (예: D-3, D-DAY, 상시모집)")
    d_day_status: str = Field(default="", description="D- | D+ | 상시")
    deadline: Optional[str] = Field(None, description="ISO 마감일 YYYY-MM-DD")
    deadline_display: str = Field(default="", description="표시용 마감일 (예: 2026년 6월 14일 (일))")
    days_remaining: Optional[int] = Field(None, description="남은 일수")
    is_live: bool = Field(default=True, description="지원 가능 여부 (D+ 제외)")


class SourceRef(BaseModel):
    """타임라인 페이즈별 실시간 소싱 참조."""
    source_platform: str
    title: str
    link_url: Optional[str] = None
    keyword_match: str = ""
    d_day_label: str = ""
    d_day_status: str = ""
    deadline: Optional[str] = None
    deadline_display: str = ""
    days_remaining: Optional[int] = None
    is_live: bool = True


class ActionGroup(BaseModel):
    category: str = Field(..., description="분류 (예: 봉사활동, 어학, 직무 기초 지식 등)")
    items: List[str] = Field(default_factory=list, description="분류별 행동 지침 목록")


class RoadmapMilestone(BaseModel):
    """4-Phase 고정 커리어 마스터 타임라인 마일스톤."""
    phase_num: int = Field(..., ge=1, le=4, description="1~4 고정")
    phase_title: str
    period: str
    narrative_bridge_directive: str = ""
    actions: List[str] = Field(default_factory=list)
    action_groups: List[ActionGroup] = Field(default_factory=list, description="카테고리별로 세분화된 행동 지침 (존재 시 actions보다 우선 렌더링)")
    sources: List[SourceRef] = Field(default_factory=list)
    expected_outcome: str = ""
    required_certifications: List[str] = Field(
        default_factory=list,
        description="해당 Phase에서 취득·준비해야 할 자격증명",
    )


class RequiredCertification(BaseModel):
    """로드맵상 사용자가 취득해야 하는 자격증."""
    name: str = Field(..., description="자격증명 (예: 정보처리기사, SQLD)")
    issuer: str = Field(default="", description="발행기관")
    priority: str = Field(default="권장", description="필수 | 권장 | 우대")
    target_phase: int = Field(default=3, ge=1, le=4, description="취득 목표 Phase")
    reason: str = Field(default="", description="취득 필요 사유 (합격 기준·Gap 연계)")
    status: str = Field(default="취득 필요", description="취득 필요 | 보유")


class RequiredLanguageScore(BaseModel):
    """로드맵상 사용자가 달성해야 하는 어학 점수 컷오프."""
    language_type: str = Field(..., description="어학 종류 (예: TOEIC, OPIc)")
    target_score: str = Field(..., description="목표(컷오프) 점수 또는 등급")
    current_score: str = Field(default="없음", description="사용자의 현재 점수")
    status: str = Field(default="미달", description="달성 | 미달")


class RoadmapStep(BaseModel):
    phase: str = Field(..., description="예: 'Phase 1: 성향적 진정성 확립 (1~2개월)'")
    action_items: List[str] = Field(default_factory=list, description="구체적 행동 지침 목록")
    action_groups: List[ActionGroup] = Field(default_factory=list, description="카테고리별 세부 지침 목록")
    recommended_activities: List[SourcedActivity] = Field(
        default_factory=list, description="실시간 외부 연동 추천 데이터 카드"
    )
    expected_outcome: str = Field(..., description="본 단계를 완료했을 때 획득하게 되는 담당자(Operator) 역량 서사")
    phase_title: Optional[str] = None
    narrative_bridge_directive: Optional[str] = None


class RoadmapAnalyzeResponse(BaseModel):
    success: bool
    total_gap_percentage: float
    gap_analysis_report: List[GapItem]
    timeline: List[RoadmapMilestone] = Field(default_factory=list, description="4-Phase 고정 타임라인")
    structured_roadmap: List[RoadmapStep] = Field(default_factory=list, description="레거시 호환용")
    required_certifications: List[RequiredCertification] = Field(
        default_factory=list,
        description="목표 직무 기준 사용자가 취득해야 하는 자격증 목록",
    )
    required_language_scores: List[RequiredLanguageScore] = Field(
        default_factory=list,
        description="목표 직무 기준 사용자가 달성해야 하는 어학 점수 컷오프 목록",
    )
    narrative_bridge_report: Optional[dict] = None
    dashboard_summary: Optional[dict] = Field(default=None, description="마스터 대시보드 요약 데이터")
    corporate_analysis_content: Optional[dict] = Field(
        default=None,
        description="링커리어 최신 기업분석 자료 매칭 (뷰어 URL 포함)",
    )


# --- 단계별 라우터 응답 래퍼 (HITL 중간 산출물 전달) ---
class GapStepResponse(BaseModel):
    success: bool = True
    step: int = 2
    gap_output: dict


class RoadmapBenchmarkRequest(RoadmapCriteriaRequest):
    """[신규 통합 4단계] 합격자 벤치마킹 및 갭 진단 요청."""
    pass


class BenchmarkStepResponse(BaseModel):
    success: bool = True
    step: int = 4
    benchmark_output: dict
    gap_output: dict


class RoadmapPdfRequest(BaseModel):
    """정밀 로드맵 대시보드 PDF 내보내기 요청 (프론트 대시보드 스냅샷)."""
    target_field: str
    target_company: str
    target_job: str
    user_name: str = ""
    benchmark_output: Optional[dict] = None
    gap_output: Optional[dict] = None
    roadmap_result: dict = Field(default_factory=dict)


class DashboardTopGap(BaseModel):
    rank: int
    category: str = ""
    required_criteria: str = ""
    gap_description: str = ""


class DashboardUrgentTask(BaseModel):
    rank: int
    task: str = ""


class DashboardSummaryRequest(BaseModel):
    """대시보드 요약 에이전트 요청 (최종 로드맵 완료 후 PDF 커버 생성 용)."""
    target_field: str
    target_company: str
    target_job: str
    user_name: str = ""
    gap_output: Optional[dict] = None
    benchmark_output: Optional[dict] = None
    roadmap_result: dict = Field(default_factory=dict)
    psychological_test: Optional[dict] = None


class DashboardSummaryResponse(BaseModel):
    """대시보드 요약 에이전트 결과 (PDF 1페이지 커버 데이터)."""
    success: bool = True
    executive_summary: str = ""
    top_gaps: List[DashboardTopGap] = Field(default_factory=list)
    urgent_tasks: List[DashboardUrgentTask] = Field(default_factory=list)


class DashboardChartsRequest(BaseModel):
    """matplotlib/seaborn/plotly 대시보드 차트 생성 요청."""
    target_field: str = ""
    target_company: str = ""
    target_job: str = ""
    gap_output: Optional[dict] = None
    benchmark_output: Optional[dict] = None
    dashboard_summary: Optional[dict] = None
    roadmap_result: Optional[dict] = None


class DashboardChartsResponse(BaseModel):
    """대시보드 차트 JSON (Plotly figure dict + base64 정적 이미지)."""
    success: bool = True
    plotly: dict = Field(default_factory=dict)
    static: dict = Field(default_factory=dict)
    meta: dict = Field(default_factory=dict)


class CalendarSyncRequest(BaseModel):
    """로드맵 4-Phase 타임라인을 Google Calendar에 동기화."""
    target_field: str
    target_company: str
    target_job: str
    user_name: str = ""
    roadmap_result: dict = Field(default_factory=dict)
    replace_existing: bool = Field(
        default=True,
        description="동일 로드맵 태그의 기존 일정을 삭제 후 재생성",
    )


class CalendarEventItem(BaseModel):
    event_id: str
    title: str
    start: str
    end: str
    html_link: Optional[str] = None


class CalendarSyncResponse(BaseModel):
    success: bool
    calendar_id: str
    created_count: int
    deleted_count: int = 0
    events: List[CalendarEventItem] = Field(default_factory=list)
    message: str = ""


class CalendarAddContestRequest(BaseModel):
    """공모전/대외활동 마감 일정 단건 등록."""
    title: str = Field(..., min_length=1, description="공모전 제목")
    url: str = Field(default="", description="상세 페이지 URL")
    date: str = Field(..., description="마감일 YYYY-MM-DD")


class CalendarAddContestResponse(BaseModel):
    success: bool
    calendar_id: str
    event_id: str
    title: str
    start: str
    end: str
    html_link: Optional[str] = None
    message: str = ""
