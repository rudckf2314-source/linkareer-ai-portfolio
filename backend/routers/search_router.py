"""[Controller Layer] 자동완성·기업분석 매칭 라우터."""
from fastapi import APIRouter, HTTPException, Query

from core.models import (
    KeywordSuggestResponse, KeywordSuggestionItem,
    CompanyAnalysisMatchRequest, CompanyAnalysisMatchResponse, CorporateAnalysisContent,
    CompanyAnalysisSuggestResponse,
)
from services.autocomplete_service import autocomplete_service
from services.company_analysis_service import company_analysis_service

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/autocomplete/keywords", response_model=KeywordSuggestResponse)
async def autocomplete_keywords(
    q: str = Query("", max_length=80),
    context: str = Query("job", pattern="^(job|field|company)$"),
):
    """고용24 등 연동 API 용어 기반 자동완성 (병렬 조회)."""
    items = autocomplete_service.suggest(q, context=context)
    return KeywordSuggestResponse(
        query=q.strip(), context=context,
        suggestions=[KeywordSuggestionItem(**item) for item in items],
    )


@router.post("/company-analysis/match", response_model=CompanyAnalysisMatchResponse)
async def match_company_analysis(payload: CompanyAnalysisMatchRequest):
    """분야·직무·기업 기준 최신 링커리어 기업분석 자료 1건 매칭."""
    company = payload.target_company.strip()
    if not company:
        raise HTTPException(status_code=400, detail="target_company는 필수입니다.")
    raw = company_analysis_service.match_latest(
        target_company=company,
        target_job=payload.target_job.strip(),
        target_field=payload.target_field.strip(),
    )
    content = raw.get("corporate_analysis_content") or {}
    return CompanyAnalysisMatchResponse(
        search_context=raw.get("search_context") or {},
        corporate_analysis_content=CorporateAnalysisContent(**content),
        related_searches=raw.get("related_searches") or [],
    )


@router.get("/company-analysis/suggest", response_model=CompanyAnalysisSuggestResponse)
async def suggest_company_analysis(q: str = Query("", max_length=80)):
    """기업분석 탭 연관 검색어 — 링커리어 등록 기업만 추천."""
    query = q.strip()
    items = company_analysis_service.suggest(query)
    return CompanyAnalysisSuggestResponse(query=query, suggestions=items)


@router.get("/company-analysis/match", response_model=CompanyAnalysisMatchResponse)
async def match_company_analysis_get(
    target_company: str = Query(..., min_length=1),
    target_job: str = Query(""),
    target_field: str = Query(""),
):
    """GET 단축 — 기업분석 탭·대시보드 위젯용."""
    return await match_company_analysis(CompanyAnalysisMatchRequest(
        target_company=target_company.strip(),
        target_job=target_job.strip(),
        target_field=target_field.strip(),
    ))
