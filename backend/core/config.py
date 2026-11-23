"""[Config] 시스템 전역 환경 변수 관리 (Settings 싱글톤)."""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """애플리케이션 전역 설정. .env 값을 단일 진입점으로 캡슐화한다."""

    # ----- AI / LLM -----
    OPENAI_API_KEY: str | None = os.environ.get("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    # ----- Search -----
    TAVILY_API_KEY: str | None = os.environ.get("TAVILY_API_KEY")
    SERPER_API_KEY: str | None = os.environ.get("SERPER_API_KEY")

    # ----- 커리어넷 (보조 진로 데이터) -----
    CAREERNET_API_KEY: str | None = os.environ.get("CAREERNET_API_KEY")
    CAREERNET_OPENAPI_BASE: str = "https://www.career.go.kr/cnet/openapi/getOpenApi"
    CAREERNET_JUNIOR_BASE: str = "https://www.career.go.kr/cnet/front/openapi"

    # ----- 고용24(Work24) Open API -----
    WORKNET_API_KEY_WANTED: str | None = os.environ.get("WORKNET_API_KEY_WANTED")
    WORKNET_API_KEY_JOB: str | None = os.environ.get("WORKNET_API_KEY_JOB")
    WORKNET_API_KEY_DUTY: str | None = os.environ.get("WORKNET_API_KEY_DUTY")
    WORKNET_API_KEY_MAJOR: str | None = os.environ.get("WORKNET_API_KEY_MAJOR")
    WORKNET_API_KEY_GANGSO: str | None = os.environ.get("WORKNET_API_KEY_GANGSO")
    WORKNET_API_KEY_TRAINING_BIZ: str | None = os.environ.get("WORKNET_API_KEY_TRAINING_BIZ")
    WORKNET_API_KEY_TRAINING_WORK: str | None = os.environ.get("WORKNET_API_KEY_TRAINING_WORK")
    WORKNET_API_KEY_TRAINING_NBC: str | None = os.environ.get("WORKNET_API_KEY_TRAINING_NBC")
    WORKNET_API_KEY_TRAINING_CONSORTIUM: str | None = os.environ.get("WORKNET_API_KEY_TRAINING_CONSORTIUM")
    WORKNET_API_KEY_TRAINING_JOBSEEKER: str | None = os.environ.get("WORKNET_API_KEY_TRAINING_JOBSEEKER")
    WORKNET_API_KEY_COMMON: str | None = os.environ.get("WORKNET_API_KEY_COMMON")
    WORKNET_API_KEY_KDT: str | None = os.environ.get("WORKNET_API_KEY_KDT")
    WORK24_API_BASE: str = "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo"

    # ----- Google Calendar (서버 내부 OAuth — refresh token 사전 등록) -----
    GOOGLE_CLIENT_ID: str | None = os.environ.get("GOOGLE_CLIENT_ID", "").strip('"') or None
    GOOGLE_CLIENT_SECRET: str | None = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip('"') or None
    GOOGLE_REFRESH_TOKEN: str | None = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip('"') or None
    GOOGLE_CALENDAR_ID: str = os.environ.get("GOOGLE_CALENDAR_ID", "primary").strip('"') or "primary"

    # ----- 원티드 합격 이력서 API (선택) -----
    WANTED_JWT_TOKEN: str | None = os.environ.get("WANTED_JWT_TOKEN", "").strip().strip('"') or None

    # ----- Server -----
    SERVER_HOST: str = os.environ.get("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.environ.get("SERVER_PORT", 8000))
    CREW_VERBOSE: bool = os.environ.get("CREW_VERBOSE", "true").lower() in ("1", "true", "yes")

    @property
    def google_calendar_ready(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET and self.GOOGLE_REFRESH_TOKEN)

    def validate(self) -> None:
        if not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY가 .env 파일에 설정되지 않았습니다.")
        if not self.TAVILY_API_KEY:
            raise ValueError("TAVILY_API_KEY가 .env 파일에 설정되지 않았습니다.")


# 전역 싱글톤 인스턴스
settings = Settings()
settings.validate()
