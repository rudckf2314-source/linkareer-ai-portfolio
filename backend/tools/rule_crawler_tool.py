"""
[Infrastructure] Rule-based 직접 크롤러 — crawler_rules.py 규칙만 사용.

공모전: 링커리어, 위비티
인턴:  사람인, 원티드(JSON API)
"""
from __future__ import annotations

import json
from datetime import date
import random
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from core.crawler_rules import (
    CONTEST_TARGETS,
    INTERNSHIP_TARGETS,
    CrawlerTarget,
    DEFAULT_HEADERS,
    JSON_HEADERS,
    build_list_url,
    build_wanted_jobs_api_url,
)
from tools.base_tool import BaseTool


class RuleCrawlerError(Exception):
    pass


def _relaxed_keyword_match(title: str, keyword: str) -> bool:
    """제목·키워드 부분 일치 (공모전·인턴 제목에 직무명이 없는 경우 대비)."""
    if not (keyword or "").strip():
        return True
    blob = (title or "").lower()
    kw = keyword.strip().lower()
    if kw in blob:
        return True
    parts = [p for p in re.split(r"[\s,/]+", kw) if len(p) >= 2]
    if not parts:
        return True
    return any(p in blob for p in parts)


def _sleep(target: CrawlerTarget) -> None:
    lo, hi = target.request_delay_sec
    if hi > 0:
        time.sleep(random.uniform(lo, hi))


def _normalize_item(
    target: CrawlerTarget,
    title: str,
    link: str,
    snippet: str = "",
    keyword: str = "",
    *,
    end_date: str = "",
) -> dict:
    item = {
        "source_platform": target.source_platform,
        "title": title.strip(),
        "link": link.strip(),
        "link_url": link.strip(),
        "snippet": (snippet or "")[:300],
        "keyword_match": keyword,
    }
    if end_date:
        item["end_date"] = end_date
        item["deadline"] = end_date
    return item


class RuleCrawlerTool(BaseTool):
    """crawler_rules 고정 URL·파싱 경로로 공모전/인턴 리스트 수집."""

    name = "rule_crawler_tool"

    def _get(self, url: str, *, json_mode: bool = False, target: CrawlerTarget | None = None) -> requests.Response:
        headers = JSON_HEADERS if json_mode else DEFAULT_HEADERS
        if target:
            _sleep(target)
        return requests.get(url, headers=headers, timeout=20)

    def _parse_linkareer(
        self,
        target: CrawlerTarget,
        html: str,
        keyword: str,
        *,
        apply_keyword_filter: bool = True,
    ) -> list[dict]:
        rule = target.parse
        m = re.search(
            rf'<script id="{rule.next_data_script_id}"[^>]*>(.*?)</script>',
            html,
            re.S,
        )
        if not m:
            return []
        data = json.loads(m.group(1))
        node: Any = data
        for key in rule.apollo_state_path:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        if not isinstance(node, dict):
            return []

        out: list[dict] = []
        for val in node.values():
            if not isinstance(val, dict):
                continue
            if val.get("__typename") != rule.apollo_typename:
                continue
            title = str(val.get(rule.apollo_title_field) or "").strip()
            act_id = val.get(rule.apollo_id_field)
            if not title or act_id is None:
                continue
            link = rule.detail_url_template.format(id=act_id)
            closes = val.get("closesAt") or val.get("closeAt") or val.get("deadline") or ""
            snippet_parts = []
            end_date = ""
            if closes:
                snippet_parts.append(f"마감: {closes}")
                date_m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", str(closes))
                if date_m:
                    try:
                        end_date = f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}"
                        end = date(int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3)))
                        delta = (end - date.today()).days
                        if delta >= 0:
                            snippet_parts.append(f"D-{delta}")
                    except ValueError:
                        end_date = ""
            snippet = " ".join(snippet_parts)
            if apply_keyword_filter and keyword and not _relaxed_keyword_match(title, keyword):
                continue
            out.append(_normalize_item(target, title, link, snippet, keyword, end_date=end_date))
        return out

    def _parse_wevity(
        self,
        target: CrawlerTarget,
        html: str,
        keyword: str,
        *,
        apply_keyword_filter: bool = True,
    ) -> list[dict]:
        rule = target.parse
        soup = BeautifulSoup(html, "html.parser")
        out: list[dict] = []
        for a in soup.select(rule.list_selector):
            href = (a.get(rule.link_attr) or "").strip()
            title = a.get_text(strip=True)
            if not href or not title or len(title) < 4:
                continue
            if "gbn=view" in href or "c=view" in href or "ix=" in href:
                if href.startswith("?"):
                    link = urljoin("https://www.wevity.com/", href)
                elif href.startswith("http"):
                    link = href
                else:
                    link = rule.link_prefix.rstrip("/") + "/" + href.lstrip("/")
            else:
                continue
            if apply_keyword_filter and keyword and not _relaxed_keyword_match(title, keyword):
                continue
            out.append(_normalize_item(target, title, link, "", keyword))
        return out

    def _parse_saramin(self, target: CrawlerTarget, html: str, keyword: str) -> list[dict]:
        rule = target.parse
        soup = BeautifulSoup(html, "html.parser")
        out: list[dict] = []
        seen: set[str] = set()
        for a in soup.select(rule.list_selector):
            href = (a.get(rule.link_attr) or "").strip()
            if not href or "rec_idx" not in href:
                continue
            if href in seen:
                continue
            seen.add(href)
            tit_el = a.select_one(rule.title_selector) if rule.title_selector else None
            title = (tit_el or a).get_text(strip=True)
            if not title:
                continue
            if keyword:
                if not _relaxed_keyword_match(title, keyword):
                    continue
            link = href if href.startswith("http") else urljoin(rule.link_prefix, href)
            out.append(_normalize_item(target, title, link, "", keyword))
        return out

    def _parse_wanted_api(
        self,
        target: CrawlerTarget,
        data: dict,
        keyword: str,
        *,
        apply_keyword_filter: bool = True,
    ) -> list[dict]:
        rule = target.parse
        jobs: Any = data
        for key in rule.api_response_jobs_path:
            if isinstance(jobs, dict):
                jobs = jobs.get(key, [])
            else:
                break
        if not isinstance(jobs, list):
            return []

        out: list[dict] = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            title = ""
            for field in rule.api_title_fields:
                if job.get(field):
                    title = str(job[field]).strip()
                    break
            job_id = job.get(rule.api_id_field)
            if not title or job_id is None:
                continue
            company = job.get("company") or {}
            company_name = company.get("name") if isinstance(company, dict) else ""
            blob = f"{title} {company_name}".strip()
            if apply_keyword_filter and keyword and not _relaxed_keyword_match(blob, keyword):
                continue
            # Phase 4: 인턴·인턴십 공고만 (신입 단독 채용 제외)
            if not re.search(r"(인턴|인턴십|internship|\bintern\b)", blob, re.I):
                continue
            link = rule.api_detail_url_template.format(id=job_id)
            snippet = f"회사: {company_name}" if company_name else ""
            out.append(_normalize_item(target, title, link, snippet, keyword))
        return out

    def fetch_target(
        self,
        target: CrawlerTarget,
        *,
        keyword: str = "",
        field: str = "",
        job: str = "",
        limit: int = 8,
        apply_keyword_filter: bool | None = None,
    ) -> list[dict]:
        """단일 타겟 규칙으로 리스트 수집."""
        if apply_keyword_filter is None:
            # 링커리어 공모전·원티드: 사전 필터 URL/query로 수집, 제목 키워드 필터 생략
            apply_keyword_filter = target.site_id not in (
                "linkareer_contest",
                "wanted_intern_backend",
            )
        try:
            if target.parse.method == "json_api" and target.site_id == "wanted_intern_backend":
                api_url = build_wanted_jobs_api_url(field=field, job=job, limit=max(limit, 16))
                res = self._get(api_url, json_mode=True, target=target)
                res.raise_for_status()
                return self._parse_wanted_api(
                    target, res.json(), keyword, apply_keyword_filter=apply_keyword_filter,
                )[:limit]

            url = build_list_url(target, keyword=keyword)
            if target.site_id == "linkareer_contest":
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}filter_ids=it-sw-game-web-app"

            res = self._get(url, target=target)
            res.raise_for_status()
            html = res.text

            if target.parse.method == "next_apollo":
                items = self._parse_linkareer(
                    target, html, keyword, apply_keyword_filter=apply_keyword_filter,
                )
            elif target.site_id == "wevity_contest_it":
                items = self._parse_wevity(
                    target, html, keyword, apply_keyword_filter=apply_keyword_filter,
                )
            elif target.site_id == "saramin_intern":
                items = self._parse_saramin(target, html, keyword)
            else:
                items = []

            return items[:limit]
        except Exception:
            return []

    def fetch_contests(self, *, keyword: str = "", limit_per_site: int = 6) -> list[dict]:
        """Phase 3 — 링커리어(IT/SW 공모전) + 위비티."""
        merged: list[dict] = []
        for target in CONTEST_TARGETS:
            # 링커리어: 키워드 없이 IT/SW 공모전 풀 전체 수집
            kw = "" if target.site_id == "linkareer_contest" else keyword
            merged.extend(self.fetch_target(target, keyword=kw, limit=limit_per_site))
        return self._post_filter(merged, require_d_tag=False)

    def fetch_internships(
        self,
        *,
        keyword: str = "",
        field: str = "",
        job: str = "",
        limit_per_site: int = 6,
    ) -> list[dict]:
        """Phase 4 — 사람인 + 원티드 인턴 (분야·직무 다중 검색어)."""
        queries: list[str] = []
        for q in [field, job, f"{field} {job}".strip(), keyword]:
            q = (q or "").strip()
            if q and q not in queries:
                queries.append(q)
        if not queries:
            queries = [""]

        merged: list[dict] = []
        for target in INTERNSHIP_TARGETS:
            if target.site_id == "wanted_intern_backend":
                merged.extend(self.fetch_target(
                    target, field=field, job=job, keyword="", limit=limit_per_site * 2,
                ))
                continue
            for q in queries:
                merged.extend(self.fetch_target(
                    target, keyword=q, field=field, job=job, limit=limit_per_site,
                ))
        ranked = self._rank_internships_by_field(merged, field=field, job=job)
        return self._post_filter(ranked, require_d_tag=False)

    @staticmethod
    def _rank_internships_by_field(
        items: list[dict],
        *,
        field: str,
        job: str,
    ) -> list[dict]:
        """분야·직무 토큰 일치도로 인턴 공고 정렬 (높은 관련성 우선)."""
        core_tokens = [
            t.lower()
            for t in re.split(r"[\s,/]+", f"{field} {job}")
            if len(t.strip()) >= 2
        ]
        skip = {"인턴", "인턴십", "채용", "공고", "신입", "모집"}

        def _score(item: dict) -> tuple[int, int]:
            blob = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
            hits = sum(1 for t in core_tokens if t not in skip and t in blob)
            field_hits = sum(
                1 for t in re.split(r"[\s,/]+", field or "")
                if len(t) >= 2 and t.lower() in blob
            )
            return (field_hits * 2 + hits, hits)

        return sorted(items, key=lambda it: (-_score(it)[0], -_score(it)[1], it.get("title", "")))

    @staticmethod
    def _post_filter(items: list[dict], *, require_d_tag: bool) -> list[dict]:
        from core.d_day_engine import drop_expired

        seen: set[str] = set()
        deduped: list[dict] = []
        for item in items:
            key = item.get("link_url") or item.get("link") or item.get("title")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return drop_expired(deduped)

    def execute(self, query: str, **kwargs: Any) -> Any:
        from services.vector_cache_service import universal_cache

        kind = kwargs.get("kind", query)
        keyword = (kwargs.get("keyword", "") or "").strip()

        # 정규화된 kind 키
        if kind in ("contest", "contests", "공모전"):
            kind_key = "contests"
        elif kind in ("internship", "intern", "인턴"):
            kind_key = "internships"
        else:
            kind_key = "all"

        cache_key = f"rule_crawler::{kind_key}::{keyword}"
        cached = universal_cache.get_json("contexts", cache_key)
        if cached is not None:
            return cached

        if kind_key == "contests":
            result = self.fetch_contests(keyword=keyword)
        elif kind_key == "internships":
            result = self.fetch_internships(
                keyword=keyword,
                field=str(kwargs.get("field", "") or ""),
                job=str(kwargs.get("job", "") or ""),
            )
        else:
            result = {"contests": self.fetch_contests(keyword=keyword), "internships": self.fetch_internships(keyword=keyword)}

        if result:
            universal_cache.cache_json("contexts", cache_key, result)

        return result


rule_crawler_tool = RuleCrawlerTool()
