"""
Google Calendar refresh token 1회 발급 스크립트.

사용법:
  python scripts/google_calendar_auth.py

브라우저에서 Google 계정으로 1회 승인하면 refresh token이 출력됩니다.
출력된 값을 .env 의 GOOGLE_REFRESH_TOKEN 에 붙여넣으세요.

※ Google Cloud Console > API 및 서비스 > 사용자 인증 정보 > OAuth 2.0 클라이언트
   > 승인된 리디렉션 URI 에 아래 URI 를 **정확히** 추가 (끝 슬래시 포함):
     http://localhost:8090/
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

load_dotenv(os.path.join(ROOT, ".env"))

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
DEFAULT_REDIRECT_URI = "http://localhost:8090/"


def _strip(v: str | None) -> str:
    return (v or "").strip().strip('"')


def _redirect_uri() -> str:
    uri = _strip(os.getenv("GOOGLE_AUTH_REDIRECT_URI")) or DEFAULT_REDIRECT_URI
    if not uri.endswith("/"):
        uri += "/"
    return uri


def _port_from_uri(uri: str) -> int:
    parsed = urlparse(uri)
    if parsed.port:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80


def _port_owner_pid(port: int) -> int | None:
    """Windows: netstat 으로 LISTEN 중인 PID 조회."""
    if sys.platform != "win32":
        return None
    import subprocess

    try:
        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None
    for line in out.splitlines():
        if f":{port}" not in line or "LISTENING" not in line:
            continue
        parts = line.split()
        if parts and parts[-1].isdigit():
            return int(parts[-1])
    return None


def _client_config(client_id: str, client_secret: str, redirect_uri: str) -> dict:
    """Google Console OAuth 클라이언트 유형 (web | installed)."""
    kind = _strip(os.getenv("GOOGLE_OAUTH_CLIENT_TYPE")) or "web"
    key = "web" if kind == "web" else "installed"
    return {
        key: {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def _ensure_port_free(port: int) -> bool:
    pid = _port_owner_pid(port)
    if not pid:
        return True
    print(f"WARN: 포트 {port} 이(가) PID {pid} 에 의해 사용 중입니다.")
    print("      이전 auth 스크립트가 아직 실행 중일 수 있습니다.")
    if sys.platform == "win32":
        print(f"      종료: taskkill /PID {pid} /F")
    return False


def main() -> int:
    client_id = _strip(os.getenv("GOOGLE_CLIENT_ID"))
    client_secret = _strip(os.getenv("GOOGLE_CLIENT_SECRET"))
    redirect_uri = _redirect_uri()
    port = _port_from_uri(redirect_uri)

    if not client_id or not client_secret:
        print("ERROR: .env 에 GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET 이 필요합니다.")
        return 1

    client_config = _client_config(client_id, client_secret, redirect_uri)
    client_kind = "web" if "web" in client_config else "installed"

    print("=" * 60)
    print(" Google Calendar - 1회 인증 (refresh token 발급)")
    print("=" * 60)
    print(f"redirect_uri: {redirect_uri}")
    print(f"oauth_client_type: {client_kind}  (.env GOOGLE_OAUTH_CLIENT_TYPE=web|installed)")
    print()
    print("Google Cloud Console 에 위 redirect_uri 가 등록되어 있어야 합니다.")
    print("오류(redirect_uri_mismatch)가 나면 Console > OAuth 클라이언트 >")
    print("「승인된 리디렉션 URI」에 위 주소를 추가한 뒤 다시 실행하세요.")
    print()
    print("브라우저가 열리면 Calendar 권한을 승인하세요.")
    print("승인 후 아래 refresh token 을 .env 에 추가합니다:\n")
    print('  GOOGLE_REFRESH_TOKEN="<아래 값>"')
    print('  GOOGLE_CALENDAR_ID="primary"')
    print()

    if not _ensure_port_free(port):
        return 1

    flow = InstalledAppFlow.from_client_config(
        client_config, scopes=SCOPES, redirect_uri=redirect_uri
    )
    try:
        creds = flow.run_local_server(port=port, prompt="consent", access_type="offline")
    except OSError as exc:
        print(f"\nERROR: 포트 {port} 에서 로컬 서버를 열 수 없습니다: {exc}")
        pid = _port_owner_pid(port)
        if pid:
            print(f"포트 점유 PID: {pid}  →  taskkill /PID {pid} /F 후 다시 실행하세요.")
        return 1

    if not creds.refresh_token:
        print("ERROR: refresh token 을 받지 못했습니다.")
        print("Google 계정 > 보안 > 타사 앱 액세스에서 이 앱 권한을 취소한 뒤 다시 실행하세요.")
        return 1

    print("\n--- GOOGLE_REFRESH_TOKEN ---")
    print(creds.refresh_token)
    print("--- END ---\n")
    print("위 값을 .env 에 저장한 뒤 서버를 재시작하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
