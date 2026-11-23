# 캐싱 아키텍처 문서

> 최종 업데이트: 2026-06-14 (v5)

---

## 개요

캐시 레이어 4개로 구성.

| 레이어               | 구현                                                      | 저장 위치                                    | TTL            |
| -------------------- | --------------------------------------------------------- | -------------------------------------------- | -------------- |
| LLM 대화 결과        | `LLMCache` (JSON 파일)                                    | `cache/llm_cache.json`                       | 없음 (영구)    |
| 사용자 데이터 파일   | `CacheService` (JSON 파일)                                | `cache/hopeCareer_cash/`, `cache/spec_cash/` | 없음 (영구)    |
| 벡터 DB KV (정확 키) | `UniversalCacheService.cache/get`                         | `backend/vector_db/` (ChromaDB)              | 도메인별 6~48h |
| 벡터 DB RAG (시맨틱) | `UniversalCacheService.cache_activities/query_activities` | `backend/vector_db/` (ChromaDB)              | 6h             |

---

## 1. LLM 대화 결과 캐시

**파일**: `backend/services/chat_service.py` — `LLMCache` 클래스  
**저장**: `cache/llm_cache.json` (프로젝트 루트 기준)  
**방식**: 메모리 dict + 파일 영속화 (init 시 읽기, set 시 쓰기)  
**TTL**: 없음 — 수동 삭제만 가능  
**싱글톤**: `chat_service.py:39` → `llm_cache`

### 캐시 키 패턴

| 용도                  | 키 형식                               |
| --------------------- | ------------------------------------- |
| 로드맵 분야 회사 목록 | `llm_roadmap_companies_{field}_{job}` |
| 로드맵 직무 목록      | `llm_roadmap_jobs_{company}_{field}`  |

---

## 2. 사용자 데이터 파일 캐시

**파일**: `backend/services/cache_service.py` — `CacheService` 클래스  
**API**: `backend/routers/cache_router.py` → `/api/cache/*`  
**TTL**: 없음  
**싱글톤**: `cache_service.py:198` → `cache_service`

### 저장 구조

| 데이터              | 디렉토리                   | 파일명 패턴                      | API                                             |
| ------------------- | -------------------------- | -------------------------------- | ----------------------------------------------- |
| 희망 직무 탐색 결과 | `cache/hopeCareer_cash/`   | `{timestamp}_{label_slug}.json`  | `GET/POST/DELETE /api/cache/hope-career`        |
| 유저 스펙           | `cache/spec_cash/`         | `{timestamp}_{label_slug}.json`  | `GET/POST/DELETE /api/cache/spec`               |
| 심리검사 결과       | `cache/spec_cash/`         | `psychological_test_latest.json` | `GET/POST/DELETE /api/cache/psychological-test` |
| **완성된 로드맵**   | `cache/roadmap_archive/`   | `{timestamp}_{label_slug}.json`  | `GET/POST/DELETE /api/cache/roadmap-archive`    |

**심리검사 특이사항**:

- 파일 2개 동시 유지: `psychological_test_latest.json`, `psychological_test.json` (fallback)
- `save_spec()` 호출 시 최신 심리검사 결과 자동 merge됨

---

## 3. 벡터 DB 캐시 (ChromaDB)

**파일**: `backend/services/vector_cache_service.py` — `VectorCacheService` 클래스  
**저장**: `backend/vector_db/` (ChromaDB PersistentClient)  
**임베딩**: OpenAI `text-embedding-3-small` (최대 6000자 truncate)  
**싱글톤**: `vector_cache_service.py:마지막줄` → `vector_cache_service` = `universal_cache`

```python
from services.vector_cache_service import universal_cache  # v4 alias
from services.vector_cache_service import vector_cache_service  # 하위 호환
```

### 3-1. KV 캐시 (정확 키 + TTL)

도메인별로 ChromaDB 컬렉션을 지연 생성하여 정확 키로 저장.

#### 컬렉션 & TTL

| domain      | ChromaDB 컬렉션       | TTL | 저장 내용                                            |
| ----------- | --------------------- | --- | ---------------------------------------------------- |
| `jd`        | `api_raw_jd`          | 24h | JD URL Playwright 크롤링 결과, JD 구조 분석 LLM 출력 |
| `careernet` | `api_raw_careernet`   | 24h | 커리어넷 Open API 응답                               |
| `worknet`   | `api_raw_worknet`     | 24h | 워크넷 API 응답                                      |
| `criteria`  | `llm_criteria`        | 48h | Thriller_Criteria Agent LLM 출력                     |
| `gap`       | `llm_gap`             | 48h | Gap_Analyzer Agent LLM 출력                          |
| `benchmark` | `llm_benchmark`       | 48h | Spec_Benchmarker Agent LLM 출력                      |
| `contexts`  | `crawled_contexts_kv` | 6h  | 자소서 크롤링 풀, Tavily Agent 검색 결과             |

#### 키 패턴

| domain      | 키 패턴                                                    | 사용처                                    |
| ----------- | ---------------------------------------------------------- | ----------------------------------------- |
| `criteria`  | `criteria::{company}::{job}::{field}`                      | `roadmap_service.build_criteria`          |
| `benchmark` | `benchmark::{company}::{job}`                              | `roadmap_service.analyze_benchmark`       |
| `gap`       | `gap::{hash(spec[:200])}::{hash(bench[:200])}::{hash(fb)}` | `roadmap_service.analyze_gap`             |
| `jd`        | `jd::{target_url}` 또는 `jd::html::{hash(html[:400])}`     | `cache_service` JD 분석                   |
| `jd`        | `scraper::{target_url}`                                    | `agents/tools.py playwright_scraper_tool` |
| `careernet` | `careernet::{search_type}::{keyword}`                      | `careernet_tool.execute`                  |
| `contexts`  | `cover_letter::{company}::{job}`                           | `cover_letter_crawler_tool.fetch_pool`    |
| `contexts`  | `tavily_search::{hash(query)}`                             | `agents/tools.py tavily_search_tool`      |
| `contexts`  | `rule_crawler::{kind}::{keyword}`                          | `rule_crawler_tool.execute`               |

#### 공개 API 메서드

```python
# 저장 (background=True 이면 ThreadPoolExecutor 비동기)
universal_cache.cache(domain, key, text, metadata={}, background=True)
universal_cache.cache_json(domain, key, obj, background=True)

# 조회 (TTL 만료 시 None 반환 + 자동 삭제)
universal_cache.get(domain, key)        # → {"text": ..., "metadata": ...} | None
universal_cache.get_json(domain, key)   # → dict | list | None

# 관리
universal_cache.stats()                 # 도메인별 문서 수 & TTL
universal_cache.clear_domain(domain)    # 도메인 전체 삭제, 삭제 전 count 반환
```

### 3-2. 시맨틱(RAG) 캐시

#### 컬렉션 & TTL

| 컬렉션               | TTL | 저장 내용                                      |
| -------------------- | --- | ---------------------------------------------- |
| `crawled_activities` | 6h  | 공모전/채용 개별 아이템 (title, snippet, link) |
| `crawled_contexts`   | 6h  | Tavily 원문 컨텍스트 블록                      |

**TTL 적용 방식**: 저장 시 `_cached_at` 메타데이터 기록 → 조회 시 경과 시간 검사 → 만료 항목 필터

#### 공개 API 메서드

```python
# 저장
vector_cache_service.cache_activities(items, source_platform, keyword)
vector_cache_service.cache_context(query, context_text, refs)

# 조회 (시맨틱 유사도 검색)
vector_cache_service.query_activities(query, limit=12, threshold=0.9) → list[dict]
vector_cache_service.query_context(query, threshold=0.8) → (str, list[dict]) | None
```

---

## 4. 캐시 흐름도 — 요청별

### 로드맵 1단계: 합격 기준 생성 (`build_criteria`)

```
요청 → criteria KV get(criteria::{company}::{job}::{field})
    ├─ HIT  → 즉시 반환 (Tavily/LLM 생략)
    └─ MISS → Tavily 마이닝 → Thriller_Criteria Agent LLM
              → criteria KV set (48h)
              → 반환
```

### 로드맵 벤치마크: 합격자 스펙 (`analyze_benchmark`)

```
요청 → benchmark KV get(benchmark::{company}::{job})
    ├─ HIT  → 즉시 반환 (자소서 수집/LLM 생략)
    └─ MISS → cover_letter fetch_pool → contexts KV get(cover_letter::{co}::{job})
                  ├─ HIT  → 풀 재사용
                  └─ MISS → 링커리어/사람인/원티드 크롤 → contexts KV set (6h)
             → Spec_Benchmarker Agent LLM
             → benchmark KV set (48h)
             → 반환
```

### 로드맵 2단계: Gap 진단 (`analyze_gap`)

```
요청 → gap KV get(gap::{hash(spec)}::{hash(bench)}::{hash(fb)})
    ├─ HIT  → 즉시 반환 (LLM 생략)
    └─ MISS → Gap_Analyzer Agent LLM
              → gap KV set (48h)
              → 반환
```

### JD 분석 (`save_hope_career`)

```
요청 → jd KV get(jd::{url} 또는 jd::html::{hash})
    ├─ HIT  → 즉시 반환 (Playwright/LLM 생략)
    └─ MISS → JD_Structural_Analyzer Agent (Playwright + LLM)
              → jd KV set (24h)
              → 반환
```

### Playwright 스크래핑 (`playwright_scraper_tool`)

```
요청 → jd KV get(scraper::{url})
    ├─ HIT  → 즉시 반환
    └─ MISS → Playwright headless chromium
              → jd KV set (24h)
              → 반환
```

### 커리어넷 API (`careernet_tool.execute`)

```
요청 → careernet KV get(careernet::{type}::{keyword})
    ├─ HIT  → 즉시 반환
    └─ MISS → 커리어넷 HTTP API
              → 성공 시만 careernet KV set (24h)
              → 반환
```

### 공모전/인턴 크롤 (`rule_crawler_tool`)

```
요청 → contexts KV get(rule_crawler::{kind}::{keyword})  [정확 키 매치]
    ├─ HIT  → 즉시 반환 (크롤 생략)
    └─ MISS → 링커리어/위비티/사람인/원티드 HTTP 크롤
              → D-day 필터
              → contexts KV set (6h TTL)
              → 반환
```

> 이전에 시맨틱(유사도) 캐시를 적용했다가 키워드 오염(다른 키워드 결과 반환) 문제로 롤백.  
> 현재는 exact match KV 캐시만 사용 — 동일 keyword+kind 재요청 시만 hit.

---

## 5. 관리 API

`backend/routers/cache_router.py`

| 메서드 | 경로                                   | 설명                          |
| ------ | -------------------------------------- | ----------------------------- |
| GET    | `/api/cache/vector/stats`              | 컬렉션별 문서 수 & TTL        |
| DELETE | `/api/cache/vector/{domain}`           | 도메인 전체 삭제              |
| POST   | `/api/cache/vector/rag-search`         | 시맨틱 검색 테스트            |
| GET    | `/api/cache/hope-career`               | 희망 직무 캐시 목록                      |
| POST   | `/api/cache/hope-career`               | 희망 직무 저장 (JD 분석 포함)            |
| DELETE | `/api/cache/hope-career/{filename}`    | 희망 직무 삭제                           |
| GET    | `/api/cache/spec`                      | 유저 스펙 캐시 목록                      |
| POST   | `/api/cache/spec`                      | 유저 스펙 저장                           |
| DELETE | `/api/cache/spec/{filename}`           | 유저 스펙 삭제                           |
| GET    | `/api/cache/psychological-test/latest` | 최신 심리검사 결과                       |
| POST   | `/api/cache/psychological-test/upload` | 워크넷 PDF 업로드 & 파싱                 |
| DELETE | `/api/cache/psychological-test/latest` | 심리검사 결과 삭제                       |
| GET    | `/api/cache/roadmap-archive`           | 보관된 로드맵 목록                       |
| POST   | `/api/cache/roadmap-archive`           | 완성된 로드맵 저장                       |
| GET    | `/api/cache/roadmap-archive/{filename}`| 보관된 로드맵 상세 조회                  |
| DELETE | `/api/cache/roadmap-archive/{filename}`| 보관된 로드맵 삭제                       |

### `/api/cache/vector/stats` 응답 예시

```json
{
  "activities": {
    "collection": "crawled_activities",
    "count": 248,
    "ttl_hours": null
  },
  "contexts": {
    "collection": "crawled_contexts_kv",
    "count": 12,
    "ttl_hours": 6.0
  },
  "jd": { "collection": "api_raw_jd", "count": 5, "ttl_hours": 24.0 },
  "careernet": {
    "collection": "api_raw_careernet",
    "count": 3,
    "ttl_hours": 24.0
  },
  "worknet": { "collection": "api_raw_worknet", "count": 8, "ttl_hours": 24.0 },
  "criteria": { "collection": "llm_criteria", "count": 7, "ttl_hours": 48.0 },
  "gap": { "collection": "llm_gap", "count": 6, "ttl_hours": 48.0 },
  "benchmark": { "collection": "llm_benchmark", "count": 7, "ttl_hours": 48.0 }
}
```

---

## 6. 싱글톤 인스턴스 참조

| 변수명                 | 파일                      | 타입                         |
| ---------------------- | ------------------------- | ---------------------------- |
| `llm_cache`            | `chat_service.py`         | `LLMCache`                   |
| `cache_service`        | `cache_service.py`        | `CacheService`               |
| `vector_cache_service` | `vector_cache_service.py` | `VectorCacheService`         |
| `universal_cache`      | `vector_cache_service.py` | `VectorCacheService` (alias) |

---

## 7. 캐싱 안 하는 항목

| 항목                                             | 이유                                                    |
| ------------------------------------------------ | ------------------------------------------------------- |
| `navigate_service.navigate()`                    | 실시간 사용자 의도 분석 — 매 요청 입력이 다름           |
| `chat_service` 일반 대화 LLM                     | 대화형 — 동일 질문 반복 없음                            |
| `roadmap_service.synthesize_final` (run_roadmap) | 실시간 소싱 데이터 + confirmed_gap 조합 — hit rate 낮음 |
| `roadmap_service.build_dashboard_summary`        | roadmap 결과 종속 — synthesize_final과 동일 이유        |

---

## 8. 파일 구조 참조

```
backend/
├── services/
│   ├── vector_cache_service.py   # KV + RAG 캐시 핵심 (VectorCacheService)
│   ├── cache_service.py          # 파일 기반 캐시 (CacheService)
│   ├── chat_service.py           # LLMCache (llm_cache.json)
│   └── roadmap_service.py        # criteria/benchmark/gap 캐시 호출
├── tools/
│   ├── careernet_tool.py         # careernet KV 캐시
│   ├── cover_letter_crawler_tool.py  # contexts KV 캐시 (fetch_pool)
│   ├── rule_crawler_tool.py      # contexts KV 캐시 (exact keyword match, 6h)
│   ├── saramin_tool.py           # activities 시맨틱 캐시
│   ├── tavily_tool.py            # activities + contexts 시맨틱 캐시
│   └── worknet_tool.py           # contexts 시맨틱 캐시
├── agents/
│   └── tools.py                  # playwright_scraper jd캐시, tavily_search contexts캐시
├── routers/
│   └── cache_router.py           # 모든 캐시 관리 API
├── vector_db/                    # ChromaDB 영속 저장소
└── scripts/
    └── free_port.py              # 포트 해제 스크립트 (start.sh에서 호출)

cache/                            # 프로젝트 루트
├── llm_cache.json                # LLMCache 영속 저장
├── hopeCareer_cash/              # 희망 직무 JSON 파일들
├── spec_cash/                    # 스펙 + 심리검사 JSON 파일들
└── roadmap_archive/              # 완성된 로드맵 보관함 JSON 파일들
```
