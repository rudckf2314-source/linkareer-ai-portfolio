# CareerAi 시스템 아키텍처 (Mermaid)

> Mermaid 미리보기: VS Code/Cursor Mermaid 확장, GitHub, Notion, [mermaid.live](https://mermaid.live) 에 붙여넣기

---

## 1. 전체 4계층 아키텍처

```mermaid
flowchart TB
    subgraph UI["① UI Layer — frontend/index.html (사용자 인터페이스)"]
        SPEC["내 스펙 입력·L형 PDF (기본 정보 수집)"]
        HOPE["희망 직무 탐색\n분야→직무→기업 (목표 설정)"]
        RM["직무 로드맵 4~5단계 (핵심 진행 화면)"]
        HITL["HITL 정량 스펙 확인 (사용자 수동 개입 및 검토)"]
        DASH["갭 대시보드·차트·4-Phase 타임라인 (분석 결과 시각화)"]
        CHAT["AI 상담 · Agentic RPA (대화형 챗봇 도우미)"]
        ARCH["로드맵 보관함·PDF (결과물 저장 및 다운로드)"]
    end

    subgraph CTRL["② Controller Layer — FastAPI (웹 서버 및 API 라우팅)"]
        API_SPEC["/api/spec (사용자 스펙 데이터 처리)"]
        API_CACHE["/api/cache (진행 상태 및 세션 임시 저장)"]
        API_RM["/api/roadmap/* (로드맵 생성 관련 핵심 기능)"]
        API_CHAT["/api/chat (챗봇 응답 처리)"]
        API_NAV["/api/chat/navigate (챗봇의 UI 원격 조작 제어)"]
        API_CAL["/api/calendar (일정 및 캘린더 데이터 처리)"]
    end

    subgraph BIZ["③ Business / Agent Layer (핵심 비즈니스 로직 및 AI 에이전트)"]
        ORCH["roadmap_service\n(오케스트레이터 · 무상태 HITL, 파이프라인 흐름 총괄 제어)"]
        subgraph CREW["CrewAI — 순차 Crew (AI 에이전트 작업 그룹)"]
            CA["Crew A\nSpec_Benchmarker → Gap_Analyzer (합격자 데이터 비교 및 갭 분석 AI)"]
            CB["Crew B\nRoadmap_Harness → Dashboard_Summarizer (로드맵 일정 생성 및 최종 요약 AI)"]
            JD["JD_Structural_Analyzer\n(채용 공고 텍스트 구조화 분석 AI)"]
        end
        SVC["cover_letter (자소서 수집) · live_activity (활동 수집) · training_search (훈련 검색)\nrecommendation_engine (추천 엔진) · chart_service (차트 생성) · pdf_service (문서 변환)"]
    end

    subgraph INFRA["④ Infra / Guardrail Layer (기반 인프라, 데이터베이스, 외부 연동)"]
        RULE["SSOT Rules\ncrawler_rules · cover_letter_rules (크롤링 경로 및 고정 규칙)"]
        MATCH["50:30:20 matching_validator\nrelevance_gate (수집된 데이터의 적합도 필터링)"]
        DDAY["d_day_engine · activity_filter (공고 마감일 계산 및 유효성 필터링)"]
        SPEC_C["spec_classifier (어학 및 자격증 자동 분류 로직)"]
        CRAWL["Playwright · Rule Crawler (동적/정적 웹 크롤링 엔진)"]
        EXT["고용24 API · Tavily · Serper · 링커리어 (외부 검색 API 및 데이터 소스)"]
        CACHE["파일 캐시 · ChromaDB universal_cache (벡터 데이터 및 파일 저장소)"]
    end

    UI --> CTRL
    CTRL --> BIZ
    BIZ --> INFRA
    ORCH --> CA
    ORCH --> CB
    ORCH --> SVC
    SVC --> RULE
    SVC --> MATCH
    SVC --> DDAY
    SVC --> CRAWL
    CRAWL --> EXT
    ORCH --> CACHE
```

---

## 2. 직무 로드맵 핵심 파이프라인 (HITL + Crew A/B)

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant FE as "Frontend (웹 UI)"
    participant API as "FastAPI Router (API 서버)"
    participant RS as "roadmap_service (흐름 제어기)"
    participant PY as "Python Guardrails (코드 검증 로직)"
    participant CA as "Crew A (벤치마크/갭 AI)"
    participant CB as "Crew B (로드맵/요약 AI)"

    U->>FE: 희망직무·스펙 캐시 선택 적용
    U->>FE: 4단계 벤치마킹 실행
    FE->>API: POST /api/roadmap/benchmark (벤치마크 요청)
    API->>RS: analyze_benchmark_and_gap() (벤치마크 및 갭 분석 통합 실행)

    RS->>PY: 합격자소서 크롤 + 50:30:20 매칭 (적합도 검증)
    PY-->>RS: cover_letters_context (검증된 합격자소서 데이터)

    RS->>CA: kickoff (순차 1회 실행)
    Note over CA: Spec_Benchmarker (스펙 비교) → Gap_Analyzer (부족 항목 진단)
    CA-->>RS: benchmark_output + gap_output (AI 분석 결과)
    RS->>PY: sanitize_benchmark (데이터 정제) · enrich_gap (누락 스펙 보완)
    RS-->>FE: 벤치마킹 + Gap Preview (사전 갭 결과 반환)

    U->>FE: HITL 수정하기 → 저장하기 / 분석 시작 (수동 검토)
    alt HITL 스펙 수정
        FE->>API: POST /api/roadmap/gap (수정된 스펙으로 갭 재분석 요청)
        API->>RS: analyze_gap() — Gap 단독 (갭 분석만 다시 실행)
        RS->>CA: run_gap() only (Gap_Analyzer 만 실행)
    else 수정 없음
        FE->>FE: preliminaryGap 재사용 (기존 결과 그대로 사용)
    end

    FE-->>U: 5단계 갭 대시보드·차트 (시각화 화면 제공)

    U->>FE: 맞춤형 로드맵 생성 (최종 로드맵 요청)
    FE->>API: POST /api/roadmap/final
    API->>RS: synthesize_final() (최종 로드맵 생성 실행)

    RS->>PY: 실시간 소싱\n공모전·인턴·고용24 훈련 (활동 데이터 수집)
    PY->>PY: D-Day Drop (마감일 제외) · Phase 분류 · 50:30:20 (적합도 평가)

    RS->>CB: kickoff (순차 1회 실행)
    Note over CB: Roadmap_Harness (일정표 작성) → Dashboard_Summarizer (최종 요약)
    CB-->>RS: timeline + dashboard_summary (타임라인 및 대시보드 요약 텍스트)
    RS->>PY: _normalize_timeline (타임라인 형식 맞춤) · _sources_for_phase (강제 분배)
    RS-->>FE: 4-Phase 로드맵 + 대시보드 (최종 결과 반환)
    FE-->>U: PDF / 보관함 (다운로드 및 저장)
```

---

## 3. CrewAI 에이전트 구성 (현재 설계)

```mermaid
flowchart LR
    subgraph MAIN["로드맵 메인 파이프라인 — 4 Agents (핵심 AI 에이전트)"]
        direction TB
        B1["Spec_Benchmarker (합격자 스펙 기준점 도출)"]
        B2["Gap_Analyzer (유저 스펙과 기준점 간의 갭 분석)"]
        B3["Roadmap_Harness (분석 기반 4단계 맞춤 로드맵 생성)"]
        B4["Dashboard_Summarizer (도출된 로드맵 핵심 내용 요약)"]
        B1 -->|Crew A context| B2
        B3 -->|Crew B context| B4
    end

    subgraph SIDE["캐시 저장 전용"]
        JD["JD_Structural_Analyzer (채용공고 본문 구조화 및 핵심정보 추출)"]
    end

    subgraph BETWEEN["Crew 사이 — Python + HITL (수동/규칙 개입 구간)"]
        H["HITL 스펙 확인 (사용자 검토)"]
        S["Rule-based 소싱\nD-Day · Phase Lock (활동 수집 및 일정 강제 분류)"]
    end

    B2 --> H
    H --> S
    S --> B3

    HOPE_SAVE["희망직무 캐시 저장"] --> JD
```

---

## 4. 가드레일·Rule-based 적용 지점 (Python 규칙 강제 구간)

```mermaid
flowchart TD
    START(["사용자 입력"]) --> P1

    P1["Pydantic 스펙 검증 (입력 형식 확인)\nspec_classifier (스펙 자동 분류)"] --> P2
    P2["희망직무 저장\nJD_Structural_Analyzer (채용공고 파싱)"] --> P3
    P3["캐시 적용\nfield·job·company 필수 (데이터 유효성 확인)"] --> P4

    P4["합격자소서 SSOT 크롤 (고정 규칙 크롤링)"] --> G1{"50:30:20 매칭\nHard Drop (부적합 즉시 제외)"}
    G1 -->|Pass| CA["Crew A\n벤치마크→갭 (AI 분석)"]
    G1 -->|Fail| FB["3단계 폴백 안내 (검색 조건 확장)"]

    CA --> HITL["HITL 정량 스펙 (수동 확인/수정)"]
    HITL --> P5["갭 확정"]
    P5 --> SRC["크롤 소싱\n링커리어·사람인·고용24 (실시간 데이터 수집)"]
    SRC --> G2{"D-Day 검증\nD+ Drop (마감된 활동 제외)"}
    G2 -->|Live| CB["Crew B\n로드맵→대시보드 (AI 로드맵 생성)"]
    G2 -->|Expired| DROP["제외"]

    CB --> G3["Phase 1~4\nsources 강제 분배 (조건에 맞게 활동 리스트 재배치)"]
    G3 --> OUT(["4-Phase 로드맵\nPDF·보관함 (최종 출력물)"])
```

---

## 5. 배포·런타임 구성

```mermaid
flowchart LR
    BROWSER["Browser\nindex.html + Plotly (프론트엔드 및 차트 렌더링)"] <-->|HTTP 통신| UVICORN["uvicorn\nFastAPI main.py (백엔드 메인 서버)"]
    UVICORN --> OPENAI["OpenAI API\ngpt-4o-mini (대형 언어 모델 AI)"]
    UVICORN --> WORK24["고용24 Open API (정부 훈련 데이터 연동)"]
    UVICORN --> TAVILY["Tavily / Serper (웹 검색 엔진 API)"]
    UVICORN --> FS[("cache/\n스펙·희망직무·로드맵 (로컬 파일 저장소)")]
    UVICORN --> CHROMA[("ChromaDB\nuniversal_cache (임베딩 벡터 데이터베이스)")]
```
