"""[Business Service Layer] 워크넷 직업선호도검사(L형) PDF 파싱 및 구조화."""
import io
import re
from typing import Any

from core.models import BigFivePersonality, HollandInterest, WorknetTestResult

RIASEC_TYPES = [
    ("현실형", "R"),
    ("탐구형", "I"),
    ("예술형", "A"),
    ("사회형", "S"),
    ("진취형", "E"),
    ("관습형", "C"),
]

BIG_FIVE_LABELS = [
    ("외향성", "extraversion"),
    ("호감성", "agreeableness"),
    ("성실성", "conscientiousness"),
    ("정서적 불안정성", "neuroticism"),
    ("경험에 대한 개방성", "openness"),
    ("개방성", "openness"),
]

BIG_FIVE_DEFAULT = {
    "extraversion": 50,
    "agreeableness": 50,
    "conscientiousness": 50,
    "neuroticism": 50,
    "openness": 50,
}


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber
    except ImportError as e:
        raise RuntimeError("pdfplumber가 설치되지 않았습니다. pip install pdfplumber") from e

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text)
    combined = "\n".join(parts).strip()
    if not combined:
        raise ValueError("PDF에서 텍스트를 추출하지 못했습니다. 스캔 PDF는 OCR이 필요할 수 있습니다.")
    return combined


def _parse_int_score(text: str, label: str, code: str | None = None) -> int | None:
    patterns = []
    if code:
        patterns.append(rf"{re.escape(label)}\s*\(?\s*{code}\s*\)?[^\d]{{0,20}}(\d{{2,3}})")
    patterns.append(rf"{re.escape(label)}[^\d]{{0,24}}(\d{{2,3}})\s*(?:점|T|T점)?")
    patterns.append(rf"{re.escape(label)}[^\d]{{0,12}}T\s*(\d{{2,3}})")
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 20 <= val <= 99:
                return val
    return None


def _parse_holland(text: str) -> HollandInterest:
    raw_scores: dict[str, int] = {}
    for label, code in RIASEC_TYPES:
        score = _parse_int_score(text, label, code)
        if score is not None:
            raw_scores[code] = score

    if not raw_scores:
        raise ValueError("홀랜드(RIASEC) 흥미 점수를 PDF에서 찾지 못했습니다.")

    ranked = sorted(raw_scores.items(), key=lambda x: x[1], reverse=True)
    code_map = dict(RIASEC_TYPES)
    inv = {c: n for n, c in RIASEC_TYPES}
    highest_types = [inv[c] for c, _ in ranked[:3]]
    riasec_code = "".join(c for c, _ in ranked[:2])

    return HollandInterest(
        riasec_code=riasec_code,
        highest_types=highest_types,
        raw_scores=raw_scores,
    )


def _parse_big_five(text: str) -> BigFivePersonality:
    scores = dict(BIG_FIVE_DEFAULT)
    found = 0
    seen_openness = False
    for label, field in BIG_FIVE_LABELS:
        if field == "openness" and seen_openness:
            continue
        val = _parse_int_score(text, label)
        if val is not None:
            scores[field] = val
            found += 1
            if field == "openness":
                seen_openness = True
    if found == 0:
        raise ValueError("Big 5 성격 요인 T점수를 PDF에서 찾지 못했습니다.")
    return BigFivePersonality(**scores)


def _parse_test_date(text: str) -> str:
    m = re.search(r"(20\d{2})[\.\-/년\s]+(\d{1,2})[\.\-/월\s]+(\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(20\d{2})[\.\-/](\d{2})[\.\-/](\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def _parse_user_age(text: str) -> int:
    m = re.search(r"(?:만?\s*)?(\d{2})\s*세", text)
    if m:
        return int(m.group(1))
    m = re.search(r"연령[^\d]{0,8}(\d{2})", text)
    if m:
        return int(m.group(1))
    return 0


def _parse_desired_jobs(text: str) -> list[str]:
    jobs: list[str] = []
    block_patterns = [
        r"희망\s*직업[^\n:：]*[:：]?\s*([^\n]+)",
        r"희망직업[^\n:：]*[:：]?\s*([^\n]+)",
        r"선호\s*직업[^\n:：]*[:：]?\s*([^\n]+)",
    ]
    for pat in block_patterns:
        for m in re.finditer(pat, text):
            chunk = m.group(1).strip()
            for part in re.split(r"[,，、/|\s]{1,2}", chunk):
                p = part.strip().strip(".")
                if len(p) >= 2 and p not in jobs:
                    jobs.append(p)

    if not jobs:
        for m in re.finditer(
            r"(?:소프트웨어\s*개발(?:자)?|투자\s*분석(?:가)?|백엔드\s*개발(?:자)?|"
            r"데이터\s*(?:분석|과학)(?:자)?|기획(?:자)?|마케터|디자이너|엔지니어)",
            text,
        ):
            val = m.group(0).strip()
            if val not in jobs:
                jobs.append(val)
    return jobs[:8]


def parse_worknet_l_pdf(pdf_bytes: bytes) -> WorknetTestResult:
    """직업선호도검사(L형) PDF → WorknetTestResult."""
    text = _extract_pdf_text(pdf_bytes)
    if "직업선호" not in text and "홀랜드" not in text and "RIASEC" not in text.upper():
        if not any(k in text for k in ("현실형", "탐구형", "예술형", "외향성", "성실성")):
            raise ValueError("직업선호도검사(L형) 결과 PDF로 보이지 않습니다.")

    interest = _parse_holland(text)
    personality = _parse_big_five(text)
    return WorknetTestResult(
        test_date=_parse_test_date(text),
        user_age=_parse_user_age(text),
        stated_desired_jobs=_parse_desired_jobs(text),
        interest=interest,
        personality=personality,
    )


def worknet_test_to_summary(result: WorknetTestResult) -> str:
    """에이전트 컨텍스트용 한 줄 요약."""
    jobs = ", ".join(result.stated_desired_jobs[:3]) if result.stated_desired_jobs else "미기재"
    top = ", ".join(result.interest.highest_types[:2])
    p = result.personality
    return (
        f"Holland {result.interest.riasec_code} ({top}) | "
        f"성실성 {p.conscientiousness} 탐구연계 | 외향성 {p.extraversion} | 희망직업: {jobs}"
    )


def worknet_test_to_dict(result: WorknetTestResult) -> dict[str, Any]:
    return result.model_dump()
