"""
[Application Root] Linkareer AI Career Hub
FastAPI 앱 인스턴스 생성, 전역 CORS 미들웨어 등록, 라우터 등록만 담당한다.
비즈니스 로직은 services/, 외부 연동은 tools/, 멀티 에이전트는 agents/ 에 위치.
"""
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from core.config import settings
from routers import spec_router, roadmap_router, search_router, chat_router, cache_router, calendar_router, navigate_router

app = FastAPI(
    title="Linkareer AI Career Hub",
    description="하네스 멀티 에이전트(CrewAI) 기반 커리어 탐색·진단 API 서버",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """API 호출 시 백엔드 콘솔에 요청·응답을 즉시 출력 (캐시 목록 GET은 제외)."""
    path = request.url.path
    skip = request.method == "GET" and path.startswith("/api/cache/")
    if path.startswith("/api/") and not skip:
        print(f"[API] --> {request.method} {path}", flush=True)
        t0 = time.time()
        response = await call_next(request)
        elapsed = time.time() - t0
        print(
            f"[API] <-- {request.method} {path} {response.status_code} ({elapsed:.1f}s)",
            flush=True,
        )
        return response
    return await call_next(request)


@app.on_event("startup")
async def startup_banner():
    print("", flush=True)
    print("=" * 56, flush=True)
    print(" Linkareer AI Career Hub - backend ready", flush=True)
    print(f" URL: http://localhost:{settings.SERVER_PORT}", flush=True)
    print(f" CrewAI verbose: {'ON' if settings.CREW_VERBOSE else 'OFF'}  (.env CREW_VERBOSE)", flush=True)
    print("-" * 56, flush=True)
    print(" 이 창에 로그가 나오려면 브라우저에서 기능을 실행하세요:", flush=True)
    print("  - 정밀 로드맵(하네스) 1~3단계  ->  [HARNESS] + CrewAI 추론 로그", flush=True)
    print("  - AI 상담 챗봇              ->  LangChain 에이전트 로그", flush=True)
    print("  - PDF/스펙/검색             ->  [API] 요청 로그", flush=True)
    print("=" * 56, flush=True)
    print("", flush=True)
    sys.stdout.flush()


@app.get("/")
async def read_root():
    import os
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    return FileResponse(os.path.join(frontend_dir, "index.html"))


# 라우터 등록 (Controller Layer)
app.include_router(spec_router.router)
app.include_router(roadmap_router.router)
app.include_router(search_router.router)
app.include_router(chat_router.router)
app.include_router(cache_router.router)
app.include_router(calendar_router.router)
app.include_router(navigate_router.router)


if __name__ == "__main__":
    import os
    import uvicorn
    reload = os.environ.get("UVICORN_RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run(
        "main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=reload,
        use_colors=False,
    )
