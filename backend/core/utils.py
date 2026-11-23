"""[Shared Utility] LLM 출력 → 안전한 JSON 파싱 가드레일."""
import json
import re
from typing import Any
from urllib.parse import quote

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def attachment_disposition(filename: str) -> str:
    """PDF 등 다운로드용 Content-Disposition (latin-1 헤더 + UTF-8 filename*)."""
    fname = (filename or "download.pdf").replace('"', "").replace("\\", "_")
    ascii_name = re.sub(
        r"_+",
        "_",
        "".join(c if c.isascii() and (c.isalnum() or c in "-_.") else "_" for c in fname),
    ).strip("._") or "download.pdf"
    if fname.isascii():
        return f'attachment; filename="{ascii_name}"'
    encoded = quote(fname, safe="")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'


def safe_parse_json(text: Any) -> dict:
    """
    LLM(CrewAI) 원시 출력 문자열을 안전하게 dict 로 변환한다.

    가드레일:
    1. ```json ... ``` 마크다운 코드 블록 펜스를 제거한다.
    2. 직접 json.loads 시도.
    3. 실패 시 첫 번째 {...} 블록을 정규식으로 추출해 재시도.
    파싱 불가 시 빈 dict({}) 를 반환해 파이프라인이 락(Lock)되지 않게 한다.
    """
    if text is None:
        return {}
    if isinstance(text, dict):
        return text
    raw = str(text).strip()
    if not raw:
        return {}

    fence = _FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}
    return {}
