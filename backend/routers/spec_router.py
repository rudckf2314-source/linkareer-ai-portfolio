"""[Controller Layer] 스펙 검증 및 동적 PDF 다운로드 라우터."""
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.models import UserSpecSchema
from core.utils import attachment_disposition
from services.pdf_service import pdf_service

router = APIRouter(prefix="/api/spec", tags=["spec"])


@router.post("")
async def save_spec(spec: UserSpecSchema):
    """스펙 데이터를 Pydantic으로 검증 후 반환(저장 시뮬레이션)."""
    try:
        return {
            "success": True,
            "message": f"'{spec.basic_info.name}'님의 스펙 정보가 성공적으로 검증 및 저장되었습니다.",
            "data": spec.model_dump(),
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"데이터 처리 중 오류가 발생했습니다: {str(e)}")


@router.post("/pdf")
async def spec_pdf(spec: UserSpecSchema):
    """스펙 데이터를 스타일링된 진단서 PDF 바이너리 스트림으로 반환."""
    try:
        pdf_bytes = pdf_service.build(spec)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"PDF 생성 실패: {str(e)}")

    filename = f"{spec.basic_info.name}_spec_report.pdf"
    headers = {"Content-Disposition": attachment_disposition(filename)}
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)
