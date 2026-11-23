"""[Core] 앱 전역 기반 모듈 패키지 (설정 / 데이터 스키마 / 공용 유틸)."""
from core.config import Settings, settings
from core.utils import safe_parse_json

__all__ = ["Settings", "settings", "safe_parse_json"]
