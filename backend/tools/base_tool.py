"""[Infrastructure Tool Layer] 외부 연동 도구 추상 베이스 클래스."""
from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """
    모든 외부 API 연동 도구의 추상 베이스.

    원천 HTTP 요청(주소/키)은 구현 클래스 내부에 완전히 캡슐화되며,
    외부에서는 오직 execute() 인터페이스로만 도구를 사용한다.
    """

    #: 도구 식별 이름 (구현체에서 오버라이드)
    name: str = "base_tool"

    @abstractmethod
    def execute(self, query: str, **kwargs: Any) -> Any:
        """주어진 질의를 실행하고 가공된 결과를 반환한다."""
        raise NotImplementedError
