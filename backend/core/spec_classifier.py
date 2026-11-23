"""
[Credential Segmentation] 어학(Languages) vs 자격증(Certificates) 강제 분리.

토스(TOEIC Speaking) vs 토스(Toss 핀테크) 3단계 문맥 검증 포함.
"""
from __future__ import annotations

import re
from typing import Literal

CredentialKind = Literal["LANGUAGES", "CERTIFICATES", "CORPORATE_EXPERIENCE", "OTHER"]

_LANG_RE = re.compile(
    r"어학|"
    r"toeic\s*speaking|toeic(?:\s|$)|toeic|토익(?:스피킹)?|"
    r"opic|오픽|"
    r"toefl|토플|"
    r"ielts|"
    r"hskk?|"
    r"jlpt|jpt|sjpt|"
    r"teps|텝스|"
    r"g-?telp|지텔프|"
    r"\bspa\b|"
    r"\btsc\b|\bbct\b|"
    r"dele|delf|dalf",
    re.I,
)

_CERT_RE = re.compile(
    r"자격증|정보처리|sqld|adsp|aws|cka|기사|산업인력|license|certification|"
    r"리눅스|네트워크|정보보안|빅데이터|databricks|azure|gcp|"
    r"정처기|컴활|msa|mba|데이터분석",
    re.I,
)

_CORP_TOSS_KW = (
    "뱅크", "증권", "페이먼츠", "인턴", "팀", "도서", "대외활동", "테크", "코어",
    "비바리퍼블리카", "핀테크", "채용", "합격", "자소서", "경력", "재직", "서비스",
)

_SCORE_PATTERN = re.compile(
    r"(AL|IH|IM|IL|AM|AH|NH|NL|NM|레벨|등급|\d{2,3}\s*점)",
    re.I,
)

_TOSS_RE = re.compile(r"토스|toss", re.I)

_LANG_TYPE_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"toeic\s*speaking|토익\s*스피킹|토스", re.I), "TOEIC Speaking"),
    (re.compile(r"toeic|토익", re.I), "TOEIC"),
    (re.compile(r"opic|오픽", re.I), "OPIc"),
    (re.compile(r"toefl|토플", re.I), "TOEFL"),
    (re.compile(r"ielts", re.I), "IELTS"),
    (re.compile(r"teps|텝스", re.I), "TEPS"),
    (re.compile(r"g-?telp|지텔프", re.I), "G-TELP"),
    (re.compile(r"hskk?", re.I), "HSK"),
    (re.compile(r"jlpt", re.I), "JLPT"),
    (re.compile(r"jpt", re.I), "JPT"),
    (re.compile(r"sjpt", re.I), "SJPT"),
    (re.compile(r"\bspa\b", re.I), "SPA"),
    (re.compile(r"\btsc\b", re.I), "TSC"),
    (re.compile(r"\bbct\b", re.I), "BCT"),
    (re.compile(r"dele", re.I), "DELE"),
    (re.compile(r"delf", re.I), "DELF"),
    (re.compile(r"dalf", re.I), "DALF"),
]


def _has_toss(text: str) -> bool:
    return bool(_TOSS_RE.search(text or ""))


def _toss_corp_context(text: str) -> bool:
    return any(k in (text or "") for k in _CORP_TOSS_KW)


def _toss_score_context(text: str) -> bool:
    return bool(_SCORE_PATTERN.search(text or ""))


def classify_credential_text(
    text: str,
    *,
    target_company: str = "",
) -> CredentialKind:
    """어학 / 자격증 / 기업경력 / 기타 분류."""
    blob = (text or "").strip()
    if not blob:
        return "OTHER"

    upper = blob.upper()

    # 토스 3단계 프로토콜
    if _has_toss(blob) or "TOEIC SPEAKING" in upper:
        if _toss_corp_context(blob):
            return "CORPORATE_EXPERIENCE"
        if target_company and _has_toss(target_company) and not _toss_score_context(blob):
            return "CORPORATE_EXPERIENCE"
        if _toss_score_context(blob):
            return "LANGUAGES"
        if target_company and "토스" in target_company:
            return "CORPORATE_EXPERIENCE"
        return "OTHER"

    if _LANG_RE.search(blob):
        return "LANGUAGES"

    if _CERT_RE.search(blob):
        return "CERTIFICATES"

    return "OTHER"


def is_language_text(text: str, *, target_company: str = "") -> bool:
    return classify_credential_text(text, target_company=target_company) == "LANGUAGES"


def is_certificate_text(text: str, *, target_company: str = "") -> bool:
    return classify_credential_text(text, target_company=target_company) == "CERTIFICATES"


_CERT_SUFFIX_RE = re.compile(r"\s*자격증\s*$", re.I)

_CERT_CANONICAL: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"정처기|정보처리기사|정보처리", re.I), "정보처리기사"),
    (re.compile(r"sqld", re.I), "SQLD"),
    (re.compile(r"adsp", re.I), "ADsP"),
    (re.compile(r"컴활", re.I), "컴활"),
]


def normalize_cert_key(name: str) -> str:
    """자격증 표기 통일 — '정보처리기사 자격증' ≡ '정보처리기사'."""
    s = _CERT_SUFFIX_RE.sub("", (name or "").strip())
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    for pattern, canonical in _CERT_CANONICAL:
        if pattern.search(s):
            return canonical.lower()
    return s.lower()


def dedupe_gap_report(
    report: list[dict],
    *,
    target_company: str = "",
) -> list[dict]:
    """갭 리포트 내 동일 자격증·어학 항목 중복 제거 (높은 severity 우선 유지)."""
    sorted_rows = sorted(
        [g for g in report if isinstance(g, dict)],
        key=lambda x: -(x.get("severity_score") or 0),
    )
    out: list[dict] = []
    seen_certs: set[str] = set()
    seen_langs: set[str] = set()
    seen_other: set[str] = set()

    for g in sorted_rows:
        blob = gap_blob(g)
        label = str(g.get("required_criteria") or g.get("keyword") or "").strip()

        if is_certificate_text(blob, target_company=target_company) and not is_language_text(
            blob, target_company=target_company
        ):
            key = normalize_cert_key(label or blob)
            if not key or key in seen_certs:
                continue
            seen_certs.add(key)
        elif is_language_text(blob, target_company=target_company):
            key = extract_language_type(label or blob).lower()
            if not key or key in seen_langs:
                continue
            seen_langs.add(key)
        else:
            key = label.lower()
            if key and key in seen_other:
                continue
            if key:
                seen_other.add(key)
        out.append(g)

    return out


def extract_language_type(name: str) -> str:
    """자유 텍스트에서 어학 시험명 추출."""
    raw = (name or "").strip()
    if not raw:
        return "어학"
    for pattern, label in _LANG_TYPE_ALIASES:
        if pattern.search(raw):
            return label
    return raw[:32]


def sanitize_user_spec_dicts(
    languages: list[dict],
    certificates: list[dict],
    *,
    target_company: str = "",
) -> tuple[list[dict], list[dict]]:
    """자격증 칸에 잘못 들어간 어학 항목 → languages 강제 라우팅."""
    out_lang: list[dict] = [dict(x) for x in (languages or [])]
    out_cert: list[dict] = []

    for cert in certificates or []:
        if not isinstance(cert, dict):
            continue
        name = str(cert.get("name") or "").strip()
        blob = f"{name} {cert.get('issuer', '')}"
        kind = classify_credential_text(blob, target_company=target_company)
        if kind == "LANGUAGES":
            out_lang.append({
                "language_type": extract_language_type(name),
                "score": str(cert.get("score") or "").strip(),
                "acquisition_date": cert.get("acquisition_date") or "2020-01",
            })
            continue
        if kind == "CORPORATE_EXPERIENCE":
            continue
        out_cert.append(cert)

    clean_lang: list[dict] = []
    for lang in out_lang:
        lt = f"{lang.get('language_type', '')} {lang.get('score', '')}"
        if classify_credential_text(lt, target_company=target_company) == "CORPORATE_EXPERIENCE":
            continue
        clean_lang.append(lang)

    return clean_lang, out_cert


def sanitize_benchmark_output(
    benchmark: dict,
    *,
    target_company: str = "",
) -> dict:
    """벤치마크 정량 스펙 — 어학/자격증 버킷 교차 오염 제거."""
    out = dict(benchmark or {})
    raw_certs = out.get("common_certificates") or []
    raw_langs = out.get("average_language_scores") or []

    clean_certs: list[str] = []
    rescued_langs: list[dict] = []
    seen_cert: set[str] = set()

    for item in raw_certs:
        label = str(item).strip()
        if not label:
            continue
        if is_language_text(label, target_company=target_company):
            rescued_langs.append({"language": extract_language_type(label), "score": ""})
            continue
        if classify_credential_text(label, target_company=target_company) != "CORPORATE_EXPERIENCE":
            key = normalize_cert_key(label)
            if key and key in seen_cert:
                continue
            if key:
                seen_cert.add(key)
            clean_certs.append(label)

    clean_lang_rows: list[dict] = []
    seen_lang: set[str] = set()
    for row in list(raw_langs) + rescued_langs:
        if isinstance(row, dict):
            lang = str(row.get("language") or row.get("language_type") or "").strip()
            score = str(row.get("score") or row.get("target_score") or "").strip()
        else:
            lang, score = str(row).strip(), ""
        blob = f"{lang} {score}"
        if not lang:
            continue
        if classify_credential_text(blob, target_company=target_company) == "CERTIFICATES":
            key = normalize_cert_key(lang)
            if key and key not in seen_cert:
                seen_cert.add(key)
                clean_certs.append(lang)
            continue
        if classify_credential_text(blob, target_company=target_company) == "CORPORATE_EXPERIENCE":
            continue
        key = lang.lower()
        if key in seen_lang:
            continue
        seen_lang.add(key)
        clean_lang_rows.append({"language": lang, "score": score})

    out["common_certificates"] = clean_certs
    out["average_language_scores"] = clean_lang_rows
    return out


def gap_blob(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    return " ".join(
        str(item.get(k) or "")
        for k in ("required_criteria", "gap_description", "current_status", "keyword", "category")
    ).strip()
