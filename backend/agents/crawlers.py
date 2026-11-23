import requests
import json
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

def scrape_linkareer(url: str) -> str:
    """
    [난이도: 하] 링커리어 합격 자소서 크롤러
    로그인 없이 상세 페이지 접근 가능하며, BeautifulSoup로 빠르게 파싱 가능합니다.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        # <div> 태그 내 깔끔하게 구조화된 데이터를 텍스트로 추출
        content = soup.get_text(separator=' ', strip=True)
        return content[:5000]  # 토큰 제한을 위해 상위 5000자로 제한
    except Exception as e:
        return f"링커리어 스크래핑 실패: {str(e)}"

def scrape_saramin(url: str) -> str:
    """
    [난이도: 중] 사람인 크롤러
    fake-useragent 필수. style 속성 내의 퍼센트/숫자(차트형 데이터) 파싱을 고려합니다.
    """
    try:
        ua = UserAgent()
        headers = {"User-Agent": ua.random}
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 그래프 형태(HTML/CSS 차트)로 렌더링된 스펙 데이터에서 style 속성 파싱
        for tag in soup.find_all(style=True):
            style_str = tag.get('style', '')
            if 'width' in style_str and '%' in style_str:
                # 차트의 width 퍼센트를 텍스트로 삽입
                tag.append(f" [데이터 비율: {style_str}] ")
                
        content = soup.get_text(separator=' ', strip=True)
        return content[:5000]
    except Exception as e:
        return f"사람인 스크래핑 실패: {str(e)}"

def scrape_wanted(resume_id: str, jwt_token: str = None) -> str:
    """
    [난이도: 상] 원티드 크롤러
    Next.js 기반, SSR/CSR 혼합 구조이므로 내부 API(api/v4/resumes/)를 직접 호출합니다.
    JWT 토큰이 있어야 상세 정보 조회 가능합니다.
    """
    try:
        url = f"https://www.wanted.co.kr/api/v4/resumes/{resume_id}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"
            
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return json.dumps(data, ensure_ascii=False, indent=2)[:5000]
        else:
            return f"원티드 API 조회 실패 (상태 코드: {res.status_code}). 접근 권한(JWT 토큰)이 없거나 유효하지 않은 ID입니다."
    except Exception as e:
        return f"원티드 스크래핑 실패: {str(e)}"


def playwright_fetch_text(url: str, wait_sec: float = 2.0) -> str:
    """Playwright headless 렌더링 텍스트 추출 (사람인 등 Anti-Bot 대응)."""
    try:
        from playwright.sync_api import sync_playwright
        import time as _time
        import re as _re

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=20000)
            _time.sleep(wait_sec)
            text = page.evaluate("document.body.innerText")
            browser.close()
        return _re.sub(r"\n+", "\n", (text or "").strip())
    except Exception as e:
        return f"Playwright 스크래핑 실패: {str(e)}"
