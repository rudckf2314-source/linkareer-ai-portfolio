"""[Orchestrator Layer] HITL 인터랙티브 로드맵 엔드포인트 (상태 머신 중계).



파이프라인:

  POST /api/roadmap/benchmark → 크롤링 + Crew A(Spec_Benchmarker → Gap_Analyzer) 순차 1회

  POST /api/roadmap/gap        → (선택) HITL 피드백 반영 Gap_Analyzer 단독 재진단

  POST /api/roadmap/final      → 소싱 + Crew B(Roadmap_Harness → Dashboard_Summarizer) 순차 1회

  POST /api/roadmap/dashboard  → PDF 커버 요약 생성

  POST /api/roadmap/pdf        → 정밀 로드맵 대시보드 PDF보내기

각 단계는 무상태이며, 직전 단계의 확정 산출물을 다음 요청 페이로드로 다시 주입한다.

"""

import io



from fastapi import APIRouter, HTTPException

from fastapi.responses import StreamingResponse



from core.models import (

    RoadmapCriteriaRequest, RoadmapGapRequest, RoadmapFinalRequest,

    RoadmapAnalyzeResponse, GapStepResponse,

    RoadmapPdfRequest, DashboardSummaryRequest, DashboardSummaryResponse,

    RoadmapBenchmarkRequest, BenchmarkStepResponse,

    DashboardChartsRequest, DashboardChartsResponse,

)

from services.chart_service import chart_service

from core.utils import attachment_disposition

from services.pdf_service import pdf_service

from services.roadmap_service import roadmap_service, normalize_roadmap_pdf_payload



router = APIRouter(prefix="/api/roadmap", tags=["직무 로드맵 에이전트"])





@router.post("/gap", response_model=GapStepResponse)

async def analyze_spec_gap(payload: RoadmapGapRequest):

    """[선택] 확정 벤치마크 + 유저 피드백을 Gap_Analyzer_Agent에 주입해 공백(Gap) 자산을 재진단."""

    try:

        gap_output = roadmap_service.analyze_gap(payload)

        return GapStepResponse(success=True, step=2, gap_output=gap_output)

    except Exception as e:  # noqa: BLE001

        raise HTTPException(status_code=500, detail=f"갭 진단 에이전트 실행 실패: {str(e)}")





@router.post("/benchmark", response_model=BenchmarkStepResponse)

async def benchmark_accepted_specs(payload: RoadmapBenchmarkRequest):

    """[4단계] Rule-based 합격자소서 크롤링 → Spec_Benchmarker → Gap_Analyzer 통합 실행."""

    if not (payload.target_field.strip() and payload.target_company.strip() and payload.target_job.strip()):

        raise HTTPException(status_code=400, detail="target_field, target_company, target_job는 필수입니다.")

    try:

        benchmark_output, gap_output = roadmap_service.analyze_benchmark_and_gap(payload)

        return BenchmarkStepResponse(

            success=True, step=4,

            benchmark_output=benchmark_output,

            gap_output=gap_output

        )

    except Exception as e:

        raise HTTPException(status_code=500, detail=f"벤치마킹/갭 진단 통합 실행 실패: {str(e)}")





@router.post("/final", response_model=RoadmapAnalyzeResponse)

async def generate_final_roadmap(payload: RoadmapFinalRequest):

    """[5단계] 확정 Gap + 2차 피드백으로 외부 인프라 API를 동시 구동, 최종 액션 플랜 로드맵을 발행."""

    try:

        return roadmap_service.synthesize_final(payload)

    except Exception as e:  # noqa: BLE001

        raise HTTPException(status_code=500, detail=f"최종 로드맵 빌드 실패: {str(e)}")





@router.post("/dashboard", response_model=DashboardSummaryResponse)

async def generate_dashboard_summary(payload: DashboardSummaryRequest):

    """[대시보드 에이전트] 갭 진단·벤치마크·로드맵 전체를 종합하여 PDF 커버용 인사팀장 요약을 생성."""

    if not (payload.target_field.strip() and payload.target_company.strip() and payload.target_job.strip()):

        raise HTTPException(status_code=400, detail="target_field, target_company, target_job는 필수입니다.")

    if not payload.roadmap_result or not payload.roadmap_result.get("timeline"):

        raise HTTPException(status_code=400, detail="최종 로드맵이 생성되지 않았습니다. 최종 로드맵 생성 완료 후 다시 시도하세요.")

    try:

        result = roadmap_service.build_dashboard_summary(payload)

    except Exception as e:  # noqa: BLE001

        raise HTTPException(status_code=500, detail=f"대시보드 요약 생성 실패: {str(e)}") from e



    top_gaps = []

    raw_gaps = result.get("top_gaps") or result.get("gap_top2") or []

    for i, g in enumerate(raw_gaps[:2]):

        if isinstance(g, dict):

            top_gaps.append({

                "rank": g.get("rank", i + 1),

                "category": str(g.get("category") or ""),

                "required_criteria": str(g.get("required_criteria") or g.get("keyword") or ""),

                "gap_description": str(g.get("gap_description") or ""),

            })

        elif isinstance(g, str):

            top_gaps.append({

                "rank": i + 1,

                "category": "분석 결과",

                "required_criteria": g,

                "gap_description": "",

            })



    urgent_tasks = []

    raw_tasks = result.get("urgent_tasks") or result.get("current_month_tasks") or []

    for i, t in enumerate(raw_tasks[:3]):

        if isinstance(t, dict):

            urgent_tasks.append({"rank": t.get("rank", i + 1), "task": str(t.get("task") or "")})

        elif isinstance(t, str):

            urgent_tasks.append({"rank": i + 1, "task": t})



    exec_summary = str(result.get("executive_summary") or result.get("total_summary") or "")



    return DashboardSummaryResponse(

        success=True,

        executive_summary=exec_summary,

        top_gaps=top_gaps,

        urgent_tasks=urgent_tasks,

    )





@router.post("/charts", response_model=DashboardChartsResponse)

async def generate_dashboard_charts(payload: DashboardChartsRequest):

    """Gap·벤치마크·로드맵 데이터를 matplotlib/seaborn/plotly 차트로 시각화."""

    if not payload.gap_output and not payload.benchmark_output:

        raise HTTPException(status_code=400, detail="gap_output 또는 benchmark_output 중 하나는 필요합니다.")

    try:

        result = chart_service.build_dashboard_charts(

            gap_output=payload.gap_output,

            benchmark_output=payload.benchmark_output,

            dashboard_summary=payload.dashboard_summary,

            roadmap_result=payload.roadmap_result,

            target_field=payload.target_field,

            target_job=payload.target_job,

            target_company=payload.target_company,

        )

    except Exception as e:  # noqa: BLE001

        raise HTTPException(status_code=500, detail=f"대시보드 차트 생성 실패: {str(e)}") from e

    return DashboardChartsResponse(success=True, **result)





@router.post("/pdf")

async def export_roadmap_pdf(payload: RoadmapPdfRequest):

    """정밀 로드맵 대시보드(벤치마크·Gap·4-Phase) PDF 리포트 다운로드."""

    if not (payload.target_field.strip() and payload.target_company.strip() and payload.target_job.strip()):

        raise HTTPException(status_code=400, detail="target_field, target_company, target_job는 필수입니다.")

    if not payload.roadmap_result or not isinstance(payload.roadmap_result, dict) or not payload.roadmap_result.get("timeline"):

        raise HTTPException(status_code=400, detail="최종 로드맵이 생성되지 않았습니다. 최종 로드맵 생성 완료 후 다시 시도하세요.")

    try:

        safe_payload = RoadmapPdfRequest(

            target_field=payload.target_field.strip(),

            target_company=payload.target_company.strip(),

            target_job=payload.target_job.strip(),

            user_name=payload.user_name or "",

            benchmark_output=payload.benchmark_output,

            gap_output=payload.gap_output,

            roadmap_result=normalize_roadmap_pdf_payload(payload.roadmap_result),

        )

        pdf_bytes = pdf_service.build_roadmap_dashboard(safe_payload)

    except Exception as e:  # noqa: BLE001

        raise HTTPException(status_code=500, detail=f"PDF 생성 실패: {str(e)}") from e



    raw_name = (payload.user_name or payload.target_company or "roadmap").strip()

    filename = f"{raw_name}_career_roadmap.pdf"

    headers = {"Content-Disposition": attachment_disposition(filename)}

    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)

