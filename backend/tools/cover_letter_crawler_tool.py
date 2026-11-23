"""Rule-based 합격 자소서 직접 크롤러."""
from __future__ import annotations

import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from agents.crawlers import scrape_linkareer, scrape_saramin, scrape_wanted, playwright_fetch_text
from core.config import settings
from core.cover_letter_rules import (
    ALLOWED_DOMAINS,
    COVER_LETTER_TARGETS,
    CoverLetterTarget,
    DEFAULT_HEADERS,
    JSON_HEADERS,
    LINKAREER_COVER_LETTER,
    SARAMIN_COVER_LETTER,
    WANTED_COVER_LETTER,
    build_cover_letter_list_url,
)
from services.recommendation_engine import recommendation_engine
from tools.base_tool import BaseTool


class CoverLetterCrawlerError(Exception):
    pass


def _sleep(target: CoverLetterTarget) -> None:
    lo, hi = target.request_delay_sec
    if hi > 0:
        time.sleep(random.uniform(lo, hi))


def _allowed_url(url: str) -> bool:
    return any(d in (url or "") for d in ALLOWED_DOMAINS)


def _item(
    target: CoverLetterTarget,
    *,
    title: str,
    url: str,
    company: str = "",
    snippet: str = "",
    content: str = "",
) -> dict:
    return {
        "source_platform": target.source_platform,
        "title": title.strip(),
        "url": url.strip(),
        "company": (company or "").strip(),
        "snippet": (snippet or "")[:400],
        "content": (content or "")[:3000],
    }


class CoverLetterCrawlerTool(BaseTool):
    name = "cover_letter_crawler_tool"

    def _fetch_linkareer(
        self,
        *,
        company: str = "",
        role_id: str = "",
        limit: int = 20,
    ) -> list[dict]:
        target = LINKAREER_COVER_LETTER
        url = build_cover_letter_list_url(target, company=company, role_id=role_id)
        try:
            res = requests.get(url, headers=DEFAULT_HEADERS, timeout=20)
            res.raise_for_status()
        except Exception:
            return []

        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            res.text,
            re.S,
        )
        if not m:
            return []

        apollo = (
            json.loads(m.group(1))
            .get("props", {})
            .get("pageProps", {})
            .get("__APOLLO_STATE__", {})
        )
        rule = target.parse
        out: list[dict] = []
        for val in apollo.values():
            if not isinstance(val, dict):
                continue
            if val.get("__typename") != rule.apollo_typename:
                continue
            cid = val.get(rule.apollo_id_field)
            org = str(val.get(rule.apollo_company_field) or "").strip()
            title = str(val.get(rule.apollo_title_field) or "").strip()
            if not cid:
                continue
            if company.strip():
                comp = company.strip()
                if org and comp not in org and org not in comp:
                    continue
            if not title:
                title = f"{org} 합격 자소서" if org else f"합격 자소서 #{cid}"
            detail = rule.detail_url_template.format(id=cid)
            if not _allowed_url(detail):
                continue
            out.append(_item(target, title=title, url=detail, company=org))
            if len(out) >= limit:
                break
        return out

    def _scrape_detail(self, item: dict) -> dict:
        url = item.get("url", "")
        if "linkareer.com/cover-letter/" in url:
            body = scrape_linkareer(url)
            if body and not body.startswith("링커리어 스크래핑 실패"):
                item["content"] = body[:3000]
        elif "saramin.co.kr" in url:
            body = scrape_saramin(url)
            if body and not body.startswith("사람인 스크래핑 실패"):
                item["content"] = body[:3000]
        elif "wanted.co.kr" in url:
            rid = url.rstrip("/").split("/")[-1]
            token = getattr(settings, "WANTED_JWT_TOKEN", None)
            body = scrape_wanted(rid, jwt_token=token)
            if body and "실패" not in body:
                item["content"] = body[:3000]
        return item

    def _fetch_saramin(self, *, company: str = "", limit: int = 10) -> list[dict]:
        target = SARAMIN_COVER_LETTER
        url = build_cover_letter_list_url(target, company=company)
        _sleep(target)
        try:
            res = requests.get(url, headers=DEFAULT_HEADERS, timeout=20)
            if res.status_code == 404:
                return self._fetch_saramin_playwright(company=company, limit=limit)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
        except Exception:
            return self._fetch_saramin_playwright(company=company, limit=limit)

        out: list[dict] = []
        seen: set[str] = set()
        for a in soup.select('a[href*="rec_idx"], a[href*="cover"]'):
            href = (a.get("href") or "").strip()
            if not href or href in seen:
                continue
            seen.add(href)
            title = a.get_text(strip=True)
            if len(title) < 4:
                continue
            if company.strip() and company.strip() not in title:
                continue
            link = href if href.startswith("http") else urljoin(target.parse.link_prefix, href)
            if not _allowed_url(link):
                continue
            out.append(_item(target, title=title, url=link, company=company))
            if len(out) >= limit:
                break
        return out

    def _fetch_saramin_playwright(self, *, company: str = "", limit: int = 10) -> list[dict]:
        target = SARAMIN_COVER_LETTER
        url = build_cover_letter_list_url(target, company=company)
        text = playwright_fetch_text(url)
        if not text or text.startswith("Playwright"):
            return []
        out: list[dict] = []
        for line in text.split("\n"):
            line = line.strip()
            if len(line) < 8:
                continue
            if "자소서" not in line and "합격" not in line:
                continue
            out.append(_item(target, title=line[:120], url=url, company=company))
            if len(out) >= limit:
                break
        return out

    def _fetch_wanted(self, *, limit: int = 8) -> list[dict]:
        token = getattr(settings, "WANTED_JWT_TOKEN", None)
        if not token:
            return []
        target = WANTED_COVER_LETTER
        api = (
            f"{target.parse.api_url}"
            "?country=kr&job_category_id=518&job_category_tag_type_id=872&limit={limit}"
        )
        headers = {**JSON_HEADERS, "Authorization": f"Bearer {token}"}
        _sleep(target)
        try:
            res = requests.get(api.format(limit=limit), headers=headers, timeout=20)
            if not res.ok:
                return []
            data = res.json()
        except Exception:
            return []

        jobs = data.get("data") if isinstance(data, dict) else []
        if not isinstance(jobs, list):
            return []
        out: list[dict] = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            title = str(job.get("title") or job.get("name") or job.get("position") or "").strip()
            rid = job.get("id") or job.get("resume_id")
            if not title or rid is None:
                continue
            url = target.parse.detail_url_template.format(id=rid)
            if not _allowed_url(url):
                continue
            out.append(_item(target, title=title, url=url))
            if len(out) >= limit:
                break
        return out

    def fetch_pool(
        self,
        *,
        company: str = "",
        job: str = "",
        scrape_details: bool = True,
        detail_limit: int = 12,
    ) -> list[dict]:
        """3개 소스에서 자소서 풀 수집 (기업 우선 → 부족 시 직무 풀 확장)."""
        from core.cover_letter_rules import MIN_COVER_LETTER_COUNT
        from services.vector_cache_service import universal_cache

        cache_key = f"cover_letter::{(company or '').strip()}::{(job or '').strip()}"
        cached = universal_cache.get_json("contexts", cache_key)
        if isinstance(cached, list) and len(cached) >= MIN_COVER_LETTER_COUNT:
            return cached

        role_id = recommendation_engine.resolve_linkareer_role_slug(job)
        merged: list[dict] = []
        seen: set[str] = set()

        def _add_batch(batch: list[dict]) -> None:
            for item in batch:
                key = item.get("url") or item.get("title")
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)

        # 1차: 타겟 기업 + 직무
        _add_batch(self._fetch_linkareer(company=company, role_id=role_id, limit=24))
        if company.strip():
            _add_batch(self._fetch_saramin(company=company, limit=10))

        # 2차: 동일 직무 풀만 (타 기업 — 기업명 미지정 링커리어)
        if len(merged) < MIN_COVER_LETTER_COUNT:
            _add_batch(self._fetch_linkareer(company="", role_id=role_id, limit=24))

        # 3차: 원티드 API (직무 카테고리 고정)
        if len(merged) < MIN_COVER_LETTER_COUNT:
            _add_batch(self._fetch_wanted(limit=8))

        if scrape_details and merged:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {
                    pool.submit(self._scrape_detail, merged[i]): i
                    for i in range(min(detail_limit, len(merged)))
                }
                for fut in as_completed(futures):
                    idx = futures[fut]
                    try:
                        merged[idx] = fut.result()
                    except Exception:
                        pass
        if merged:
            universal_cache.cache_json("contexts", cache_key, merged)
        return merged

    def execute(self, query: str, **kwargs: Any) -> Any:
        return self.fetch_pool(
            company=kwargs.get("company", ""),
            job=kwargs.get("job", query),
        )


cover_letter_crawler_tool = CoverLetterCrawlerTool()
