import re
import json
from crewai.tools import tool
from pydantic import BaseModel, Field

class JDSchema(BaseModel):
    company_name: str
    job_title: str
    primary_duties: list[str]
    mandatory_requirements: list[str]
    preferred_qualifications: list[str]
    required_tech_stacks: list[str]

@tool("Text_Cleaner_Tool")
def text_cleaner_tool(raw_text: str) -> str:
    """
    정규표현식(Regex)을 기반으로 공고 텍스트 내의 특수문자 깨짐, 무의미한 공백, 불필요한 HTML 태그를 1차로 제거하는 내장 스크립트 도구입니다.
    이 도구에 공고 원문을 넘겨주면, 노이즈가 제거된 깔끔한 텍스트를 반환받을 수 있습니다.
    """
    if not isinstance(raw_text, str):
        return ""
    
    # HTML 태그 제거
    clean = re.sub(r'<[^>]+>', ' ', raw_text)
    # 특수문자나 깨진 글자(이모지 등) 제거, 한글/영문/숫자/기본문장부호 허용
    clean = re.sub(r'[^\w\s가-힣.,!?-]', ' ', clean)
    # 2개 이상 연속된 공백 및 줄바꿈 정리
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

@tool("Pydantic_Schema_Validator")
def pydantic_schema_validator(json_string: str) -> str:
    """
    추출된 데이터(JSON 문자열)가 반드시 지정된 JSON 구조를 따르도록 유효성을 검증하는 도구입니다.
    지정된 스키마(company_name, job_title, primary_duties, mandatory_requirements, preferred_qualifications, required_tech_stacks)가 맞는지 확인합니다.
    검증에 성공하면 유효한 JSON을 반환하고 실패하면 에러 메시지를 반환합니다.
    """
    try:
        data = json.loads(json_string)
        # Pydantic 모델로 파싱하여 구조 강제 검증
        validated = JDSchema(**data)
        return validated.model_dump_json(indent=2)
    except Exception as e:
        return f"유효성 검증 실패: {str(e)}. JSON 형식을 다시 확인해주세요."

import time
from playwright.sync_api import sync_playwright

_MIN_USEFUL_CHARS = 200  # 이 글자 수 미만이면 스크래핑 실패로 간주


@tool("Playwright_Scraper_Tool")
def playwright_scraper_tool(target_url: str) -> str:
    """
    채용 공고 URL에서 텍스트를 추출합니다.
    링커리어/사람인은 requests+BeautifulSoup, 기타 SPA 사이트는 Playwright headless를 사용합니다.
    스크래핑에 실패하면 '스크래핑 실패' 메시지를 반환합니다 — 이 경우 raw_text 입력을 직접 사용하세요.
    """
    if not target_url or not target_url.startswith("http"):
        return "유효하지 않은 URL입니다. raw_text 입력을 직접 사용하세요."

    from services.vector_cache_service import universal_cache
    cache_key = f"scraper::{target_url}"
    cached = universal_cache.get("jd", cache_key)
    if cached and len(cached["text"]) >= _MIN_USEFUL_CHARS:
        return cached["text"]

    # ── 링커리어: requests/bs4 (Playwright 봇 탐지 우회 불가)
    if "linkareer.com" in target_url:
        from agents.crawlers import scrape_linkareer
        result = scrape_linkareer(target_url)
        if result and "스크래핑 실패" not in result and len(result) >= _MIN_USEFUL_CHARS:
            universal_cache.cache("jd", cache_key, result)
            return result
        return f"링커리어 페이지 접근 불가 ({target_url}). raw_text 입력이 있으면 그것을 사용하세요."

    # ── 사람인: requests/bs4
    if "saramin.co.kr" in target_url:
        from agents.crawlers import scrape_saramin
        result = scrape_saramin(target_url)
        if result and "스크래핑 실패" not in result and len(result) >= _MIN_USEFUL_CHARS:
            universal_cache.cache("jd", cache_key, result)
            return result

    # ── 기타 SPA: Playwright headless
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto(target_url, wait_until="networkidle", timeout=15000)
            time.sleep(2)
            text_content = page.evaluate("document.body.innerText")
            browser.close()

            clean = re.sub(r'\n+', '\n', text_content).strip()
            if clean and len(clean) >= _MIN_USEFUL_CHARS:
                universal_cache.cache("jd", cache_key, clean)
                return clean
            return f"스크래핑 결과가 비어있습니다 ({target_url}). raw_text 입력이 있으면 그것을 사용하세요."
    except Exception as e:
        return f"웹 스크래핑 실패: {e}. raw_text 입력이 있으면 그것을 사용하세요."

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tools.tavily_tool import tavily_tool

@tool("Tavily_Search_Tool")
def tavily_search_tool(query: str) -> str:
    """
    링커리어, 사람인, 원티드, 고용24 등 취업/채용 포털에서 합격 자소서, 인턴 경험, 스펙 데이터를 실시간으로 검색하는 도구입니다.
    검색어(query)를 입력하면 링커리어 사이트 내의 문서 및 커뮤니티 글을 긁어와 요약해 줍니다.
    """
    import hashlib
    from services.vector_cache_service import universal_cache
    cache_key = f"tavily_search::{hashlib.md5(query.encode(), usedforsecurity=False).hexdigest()[:8]}"
    cached = universal_cache.get("contexts", cache_key)
    if cached:
        return cached["text"]

    try:
        results = tavily_tool._client().search(query=query, search_depth="advanced", max_results=10)
        output = []
        for r in results.get("results", []):
            output.append(f"[Title]: {r.get('title')}\n[Content]: {r.get('content')}\n[URL]: {r.get('url')}\n")
        text = "\n".join(output) if output else "검색 결과가 없습니다."
        if output:
            universal_cache.cache("contexts", cache_key, text)
        return text
    except Exception as e:
        return f"Tavily 검색 실패: {str(e)}"

@tool("Cover_Letter_Search_Tool")
def cover_letter_search_tool(company: str, job: str) -> str:
    """
    주어진 기업명(company)과 직무명(job)으로 합격 자소서를 Rule-based 수집합니다.
    링커리어/사람인/원티드 고정 URL에서 수집하며, 데이터 부족 시 3단계 스케일다운을 적용합니다.
    """
    try:
        from services.cover_letter_service import cover_letter_service, format_for_agent

        result = cover_letter_service.search_with_fallback(
            target_field="",
            target_company=company,
            target_job=job,
        )
        return format_for_agent(result)
    except Exception as e:
        return f"검색 실패: {str(e)}"

from agents.crawlers import scrape_linkareer, scrape_saramin, scrape_wanted

@tool("Advanced_Platform_Scraper_Tool")
def advanced_platform_scraper_tool(target_url: str) -> str:
    """
    링커리어, 사람인, 원티드 합격 자소서 상세 페이지의 URL을 입력하면,
    각 플랫폼의 특성에 맞게 엔지니어링된 크롤러(fake-useragent, 내부 API 등)를 사용해 
    실제 스펙 및 합격 자소서 데이터를 추출합니다.
    """
    if "linkareer.com" in target_url:
        return scrape_linkareer(target_url)
    elif "saramin.co.kr" in target_url:
        return scrape_saramin(target_url)
    elif "wanted.co.kr/api/v4/resumes/" in target_url:
        # URL에서 이력서 ID 추출 (예: /api/v4/resumes/12345)
        resume_id = target_url.split("/")[-1]
        return scrape_wanted(resume_id, jwt_token=None)
    else:
        # 지원하지 않는 기타 URL은 기본 파싱 또는 플레이라이트 (여기서는 안내 메시지만)
        return "지원하지 않는 URL이거나, 링커리어/사람인/원티드 상세 페이지 URL이 아닙니다. Playwright_Scraper_Tool 등을 활용해주세요."
