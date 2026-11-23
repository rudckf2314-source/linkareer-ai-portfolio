"""
[Recommendation Engine] 직무 > 분야 > 기업 계층 동적 가중치 매칭.

- 하드코딩 if-else 매핑 금지
- OpenAI 임베딩 코사인 유사도 기반
- 메타 테이블: cache/recommendation_meta.json (DB 없이 JSON 갱신)
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config import settings

_META_PATH = Path(__file__).resolve().parent.parent / "cache" / "recommendation_meta.json"
_EMBED_CACHE: dict[str, list[float]] = {}


@dataclass
class UserRecommendContext:
    job: str
    field: str
    company: str
    extra_keywords: list[str] = field(default_factory=list)

    @property
    def job_query(self) -> str:
        parts = [self.job] + self.extra_keywords
        return " ".join(p for p in parts if p).strip()

    @property
    def field_query(self) -> str:
        return (self.field or "").strip()

    @property
    def company_query(self) -> str:
        return (self.company or "").strip()


def _load_meta() -> dict:
    if _META_PATH.is_file():
        try:
            return json.loads(_META_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "score_weights": {"job_role": 0.50, "industry_domain": 0.30, "company_match": 0.20},
        "focus_priority": ["job_role", "industry_domain", "company_match"],
        "fallback_thresholds": {
            "min_items": 3,
            "tier1_min_job": 0.45,
            "tier1_min_company": 0.35,
            "tier2_min_job": 0.40,
            "tier2_min_domain": 0.35,
        },
        "linkareer_role_slugs": [],
        "company_scale_anchors": [],
        "industry_domain_anchors": [],
    }


def _tokenize(text: str) -> dict[str, float]:
    tokens = re.findall(r"[\w가-힣]{2,}", (text or "").lower())
    if not tokens:
        return {}
    freq: dict[str, float] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0.0) + 1.0
    norm = math.sqrt(sum(v * v for v in freq.values())) or 1.0
    return {k: v / norm for k, v in freq.items()}


def _cosine_vec(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in set(a) | set(b))
    return max(0.0, min(1.0, dot))


def _cosine_list(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return max(0.0, min(1.0, dot / (na * nb)))


def _embed(text: str) -> list[float]:
    key = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    if key in _EMBED_CACHE:
        return _EMBED_CACHE[key]

    if settings.OPENAI_API_KEY and (text or "").strip():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            res = client.embeddings.create(
                model="text-embedding-3-small",
                input=(text or "")[:8000],
            )
            vec = res.data[0].embedding
            _EMBED_CACHE[key] = vec
            return vec
        except Exception:
            pass

    # 폴백: 토큰 벡터를 고정 차원으로 투영 (API 불가 시)
    tokens = _tokenize(text)
    dim = 64
    vec = [0.0] * dim
    for i, (tok, w) in enumerate(tokens.items()):
        vec[i % dim] += w
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    vec = [x / norm for x in vec]
    _EMBED_CACHE[key] = vec
    return vec


def _embed_batch(texts: list[str]) -> list[list[float]]:
    missing = []
    results: dict[int, list[float]] = {}
    for i, t in enumerate(texts):
        key = hashlib.sha256((t or "").encode("utf-8")).hexdigest()
        if key in _EMBED_CACHE:
            results[i] = _EMBED_CACHE[key]
        else:
            missing.append((i, t, key))

    if missing and settings.OPENAI_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            inputs = [(t or "")[:8000] for _, t, _ in missing]
            res = client.embeddings.create(model="text-embedding-3-small", input=inputs)
            for (idx, _, key), item in zip(missing, res.data):
                vec = item.embedding
                _EMBED_CACHE[key] = vec
                results[idx] = vec
        except Exception:
            for idx, t, key in missing:
                results[idx] = _embed(t)

    for idx, t, key in missing:
        if idx not in results:
            results[idx] = _embed(t)
    return [results[i] for i in range(len(texts))]


def _item_blob(item: dict) -> str:
    return " ".join(filter(None, [
        item.get("title", ""),
        item.get("company", ""),
        item.get("snippet", ""),
        item.get("content", "")[:600],
        item.get("source_platform", ""),
        item.get("keyword_match", ""),
    ])).strip()


def _dynamic_badge(job_s: float, domain_s: float, company_s: float) -> str:
    if job_s >= max(domain_s, company_s) and job_s >= 0.5:
        return "직무 역량 우선 일치"
    if domain_s >= company_s and domain_s >= 0.4:
        return "분야 맥락 일치"
    if company_s >= 0.4:
        return "기업 규모·맥락 보조 일치"
    return "유동 매칭"


def _company_scale_score(item_blob: str, meta: dict) -> float:
    anchors = meta.get("company_scale_anchors") or []
    if not anchors:
        return 0.0
    item_vec = _embed(item_blob)
    scores = []
    for anc in anchors:
        if isinstance(anc, dict) and anc.get("text"):
            scores.append(_cosine_list(item_vec, _embed(anc["text"])))
    return max(scores) if scores else 0.0


def _domain_score(item_blob: str, ctx: UserRecommendContext, meta: dict) -> float:
    field_vec = _embed(ctx.field_query or item_blob)
    item_vec = _embed(item_blob)
    base = _cosine_list(field_vec, item_vec)

    anchors = meta.get("industry_domain_anchors") or []
    anchor_scores = []
    for anc in anchors:
        if isinstance(anc, dict) and anc.get("text"):
            anchor_scores.append(_cosine_list(item_vec, _embed(anc["text"])))
    anchor_best = max(anchor_scores) if anchor_scores else 0.0
    return max(base, anchor_best * 0.85)


class RecommendationEngine:
    """직무 > 분야 > 기업 우선순위 동적 스코어링."""

    def score_item(self, item: dict, ctx: UserRecommendContext) -> dict:
        meta = _load_meta()
        weights = meta.get("score_weights") or {}
        w_job = float(weights.get("job_role", 0.50))
        w_dom = float(weights.get("industry_domain", 0.30))
        w_co = float(weights.get("company_match", weights.get("company_scale", 0.20)))

        blob = _item_blob(item)
        job_sim = _cosine_list(_embed(ctx.job_query), _embed(blob))
        domain_sim = _domain_score(blob, ctx, meta)
        company_sim = _cosine_list(_embed(ctx.company_query), _embed(blob)) if ctx.company_query else 0.0
        scale_sim = _company_scale_score(blob, meta)
        company_combined = max(company_sim, scale_sim * 0.7) if ctx.company_query else scale_sim

        breakdown = {
            "job_role_score": round(job_sim * w_job, 4),
            "industry_domain_score": round(domain_sim * w_dom, 4),
            "company_match_score": round(company_combined * w_co, 4),
        }
        matching = round(
            breakdown["job_role_score"]
            + breakdown["industry_domain_score"]
            + breakdown["company_match_score"],
            4,
        )
        category = item.get("category") or item.get("kind") or "activity"
        return {
            **item,
            "item_id": item.get("item_id") or item.get("link_url") or item.get("url") or item.get("title"),
            "category": category,
            "matching_score": min(1.0, matching),
            "score_breakdown": breakdown,
            "dynamic_badge": _dynamic_badge(job_sim, domain_sim, company_combined),
            "_raw_similarity": {
                "job": round(job_sim, 4),
                "domain": round(domain_sim, 4),
                "company": round(company_combined, 4),
            },
        }

    def rank_items(
        self,
        items: list[dict],
        ctx: UserRecommendContext,
        *,
        limit: int = 15,
    ) -> dict:
        meta = _load_meta()
        scored = [self.score_item(it, ctx) for it in items]
        scored.sort(key=lambda x: -(x.get("matching_score") or 0))
        top = scored[:limit]
        return {
            "recommendation_context": {
                "focus_priority": meta.get("focus_priority")
                or ["job_role", "industry_domain", "company_match"],
                "is_lock_in_prevented": True,
                "user_job": ctx.job,
                "user_field": ctx.field,
                "user_company": ctx.company,
            },
            "items": top,
        }

    def select_with_fallback(
        self,
        items: list[dict],
        ctx: UserRecommendContext,
        *,
        limit: int = 15,
    ) -> dict:
        """직무+기업 → 직무+분야 → 직무 중심 3단계 스케일다운 (임베딩 기반)."""
        meta = _load_meta()
        th = meta.get("fallback_thresholds") or {}
        min_items = int(th.get("min_items", 3))
        t1_job = float(th.get("tier1_min_job", 0.45))
        t1_co = float(th.get("tier1_min_company", 0.35))
        t2_job = float(th.get("tier2_min_job", 0.40))
        t2_dom = float(th.get("tier2_min_domain", 0.35))

        ranked = self.rank_items(items, ctx, limit=max(limit, 30))
        scored = ranked["items"]

        def _raw(it: dict, key: str) -> float:
            return float((it.get("_raw_similarity") or {}).get(key, 0.0))

        tier1 = [
            it for it in scored
            if _raw(it, "job") >= t1_job and _raw(it, "company") >= t1_co
        ]
        if len(tier1) >= min_items:
            from core.matching_validator import validate_matching_batch
            validated_t1 = validate_matching_batch(tier1[:limit], ctx, fallback_level=1)
            return self._pack_fallback(validated_t1, ctx, level=1, is_fallback=False, ranked=ranked)

        tier2 = [
            it for it in scored
            if _raw(it, "job") >= t2_job and _raw(it, "domain") >= t2_dom
        ]
        if len(tier2) >= min_items:
            msg = (
                f"타겟 기업 [{ctx.company}]의 데이터가 부족하여, "
                f"동일 분야 [{ctx.field}] 맥락의 [{ctx.job}] 합격 사례를 참조 분석했습니다."
            )
            return self._pack_fallback(tier2[:limit], ctx, level=2, is_fallback=True, message=msg, ranked=ranked, is_peer_substitute=True)

        from core.relevance_gate import filter_fallback_tier3

        tier3 = filter_fallback_tier3(
            sorted(scored, key=lambda x: -_raw(x, "job")),
            ctx,
        )[:limit]
        msg = (
            f"기업·분야 매칭 데이터가 제한적이어, [{ctx.job}] 직무 역량 중심으로 "
            f"유동 매칭한 결과입니다."
        )
        return self._pack_fallback(tier3, ctx, level=3, is_fallback=True, message=msg, ranked=ranked, is_peer_substitute=True)

    @staticmethod
    def _pack_fallback(
        items: list[dict],
        ctx: UserRecommendContext,
        *,
        level: int,
        is_fallback: bool,
        message: str = "",
        ranked: dict,
        is_peer_substitute: bool = False,
    ) -> dict:
        from core.matching_validator import validate_matching_batch

        validated = validate_matching_batch(
            items,
            ctx,
            fallback_level=level,
            is_peer_substitute=is_peer_substitute,
        )
        return {
            "target_field": ctx.field,
            "target_company": ctx.company,
            "target_job": ctx.job,
            "is_fallback": is_fallback,
            "fallback_level": level,
            "fallback_message": message,
            "items": validated,
            "count": len(validated),
            "recommendation_context": ranked.get("recommendation_context", {}),
            "reference_links": [
                {"title": x.get("title", ""), "url": x.get("url") or x.get("link_url", "")}
                for x in validated if x.get("url") or x.get("link_url")
            ],
        }

    def resolve_linkareer_role_slug(self, job: str) -> str:
        """메타 테이블 임베딩 매칭으로 roleIds 동적 결정."""
        meta = _load_meta()
        slugs = meta.get("linkareer_role_slugs") or []
        if not slugs or not (job or "").strip():
            return "server-backend-developer"
        job_vec = _embed(job)
        best_slug, best_score = "server-backend-developer", -1.0
        for entry in slugs:
            if not isinstance(entry, dict):
                continue
            desc = entry.get("description") or entry.get("slug") or ""
            slug = entry.get("slug") or ""
            score = _cosine_list(job_vec, _embed(desc))
            if score > best_score and slug:
                best_score = score
                best_slug = slug
        return best_slug


recommendation_engine = RecommendationEngine()
