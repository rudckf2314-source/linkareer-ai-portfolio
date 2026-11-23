"""[Business Service Layer] 무상태(Stateless) HITL 로드맵 오케스트레이션.

Layer 1(라우터)이 단계 사이 인간 개입을 중계하고, 본 서비스는 각 단계에서
CrewAI 단일 에이전트를 가동하며 Tools Layer(Tavily/Work24/Serper) 실시간 소싱을 담당한다.
직전 단계의 확정 산출물은 요청 페이로드로 다시 주입되므로 서버 세션 상태를 보관하지 않는다.
"""
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def _h(s: str) -> str:
    """프로세스 재시작에도 안정적인 8자리 해시 (hashlib.md5)."""
    return hashlib.md5(s.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]


def _log(msg: str) -> None:
    """서버 콘솔에 진행 상황을 즉시(flush) 출력한다."""
    print(f"[HARNESS] {msg}", flush=True)
    sys.stdout.flush()

from agents.career_crew import career_crew
from core.activity_filter import (
    classify_activity_kind,
    filter_activity_dicts,
    filter_source_refs,
    is_strict_internship,
)
from services.live_activity_service import live_activity_service
from services.recommendation_engine import UserRecommendContext, recommendation_engine
from core.models import (
    RoadmapCriteriaRequest, RoadmapGapRequest, RoadmapFinalRequest,
    RoadmapAnalyzeResponse, GapItem, SourcedActivity, RoadmapStep,
    RoadmapMilestone, SourceRef, RequiredCertification,
)
from services.cache_service import cache_service
from services.vector_cache_service import universal_cache
from tools.tavily_tool import tavily_tool
from tools.worknet_tool import worknet_tool
from tools.rule_crawler_tool import rule_crawler_tool
from tools.saramin_tool import saramin_tool
from services.training_search_service import training_search_service


PHASE_SPECS = (
    {"phase_num": 1, "phase_title": "성향 분석 및 기초 역량 확립 (Psychological & Foundational Alignment)", "period": "1~2개월"},
    {"phase_num": 2, "phase_title": "직무 전문성 강화 프로젝트 수행 (Core Skill & Project Buildup)", "period": "2~3개월"},
    {"phase_num": 3, "phase_title": "실시간 공모전/부트캠프 검증 (Live Contest, Bootcamp & Project Validation)", "period": "3~4개월"},
    {"phase_num": 4, "phase_title": "포트폴리오 완성 및 취업 대비 (Portfolio & Employment Readiness)", "period": "5~6개월"},
)

from core.spec_classifier import (
    gap_blob,
    is_certificate_text,
    is_language_text,
    sanitize_benchmark_output,
    normalize_cert_key,
    dedupe_gap_report,
    extract_language_type,
)

def _clamp_int(v, default: int = 0) -> int:
    try:
        return max(0, min(100, int(float(v))))
    except Exception:
        return default


def _clamp_float(v, default: float = 0.0) -> float:
    try:
        return max(0.0, min(100.0, float(v)))
    except Exception:
        return default


class RoadmapService:
    """Spec_Benchmarker → Gap_Analyzer → (HITL) → Tools 소싱 → Roadmap_Harness."""

    def __init__(self) -> None:
        self._crew = career_crew

    @staticmethod
    def _hope_career_jd_text(payload: RoadmapCriteriaRequest) -> str:
        """희망 직무 탐색 캐시의 JD 구조화 필드를 에이전트 프롬프트용 텍스트로 변환."""
        ctx = payload.hope_career_context or {}
        if not ctx:
            return "(희망 직무 탐색 캐시 없음 — 합격자소서 벤치마크만 기준으로 분석)"

        jd = {
            "company_name": ctx.get("company_name") or ctx.get("company") or "",
            "job_title": ctx.get("job_title") or ctx.get("job") or "",
            "primary_duties": ctx.get("primary_duties") or [],
            "mandatory_requirements": ctx.get("mandatory_requirements") or [],
            "preferred_qualifications": ctx.get("preferred_qualifications") or [],
            "required_tech_stacks": ctx.get("required_tech_stacks") or [],
        }
        if not any([
            jd["primary_duties"], jd["mandatory_requirements"],
            jd["preferred_qualifications"], jd["required_tech_stacks"],
        ]):
            return "(JD 구조화 데이터 없음 — 합격자소서 벤치마크만 기준으로 분석)"
        return json.dumps(jd, ensure_ascii=False, indent=2)

    @staticmethod
    def _resolve_psychological_test(payload: RoadmapCriteriaRequest) -> dict | None:
        if payload.psychological_test:
            return payload.psychological_test
        if payload.user_spec.psychological_test:
            return payload.user_spec.psychological_test.model_dump()
        cached = cache_service.get_psychological_test_latest()
        if cached and cached.get("psychological_test"):
            return cached["psychological_test"]
        return None

    @staticmethod
    def _psych_json(payload: RoadmapCriteriaRequest) -> str:
        psych = RoadmapService._resolve_psychological_test(payload)
        if not psych:
            return "(등록된 워크넷 직업선호도검사(L형) 결과 없음 — 스펙·Gap만으로 진단)"
        return json.dumps(psych, ensure_ascii=False)

    def _dashboard_crew_inputs(self, payload, *, phase1_actions: list[str] | None = None) -> dict:
        """Dashboard_Summarizer 태스크용 입력 (Crew B 2번째 태스크)."""
        gap_output = payload.gap_output or {}
        benchmark_output = payload.benchmark_output or {}
        gap_report = sorted(
            gap_output.get("gap_analysis_report") or [],
            key=lambda x: -(x.get("severity_score") or 0) if isinstance(x, dict) else 0,
        )
        phase1_json = (
            json.dumps(phase1_actions[:5], ensure_ascii=False)
            if phase1_actions
            else "(직전 Roadmap_Harness 태스크 timeline phase_num=1 actions — Context 참조)"
        )
        return {
            "target_field": payload.target_field,
            "target_company": payload.target_company,
            "target_job": payload.target_job,
            "user_name": payload.user_name or "지원자",
            "gap_feedback": str(gap_output.get("feedback") or "(갭 진단 총평 없음)"),
            "gap_report": json.dumps(gap_report[:8], ensure_ascii=False),
            "benchmark_summary": self._benchmark_summary_text(benchmark_output),
            "benchmark_json": json.dumps(benchmark_output, ensure_ascii=False)[:6000],
            "phase1_actions": phase1_json,
        }

    # ===================================================================
    # [4단계 통합] 벤치마킹 + 갭 진단 — Crew A 순차 실행
    # ===================================================================
    def analyze_benchmark_and_gap(self, payload) -> tuple[dict, dict]:
        """Rule-based 크롤 후 Crew A(Spec_Benchmarker → Gap_Analyzer) 1회 kickoff."""
        from services.cover_letter_service import cover_letter_service, format_for_agent

        t0 = time.time()
        company = payload.target_company.strip()
        job = payload.target_job.strip()
        bench_key = f"benchmark::{company}::{job}"
        cached_bench = universal_cache.get_json("benchmark", bench_key)
        if cached_bench:
            _log(f"[벤치마크] 캐시 HIT ✅ — Gap만 단독 실행 ({time.time() - t0:.2f}s)")
            gap_payload = RoadmapGapRequest(
                **payload.model_dump(),
                benchmark_output=cached_bench,
                user_feedback_1=None,
            )
            gap = self.analyze_gap(gap_payload)
            return cached_bench, gap

        _log("[벤치마크] Rule-based 합격 자소서 수집 (스케일다운) 시작...")
        cl_search = cover_letter_service.search_with_fallback(
            target_field=payload.target_field.strip(),
            target_company=company,
            target_job=job,
        )
        _log(
            f"[벤치마크] 자소서 {cl_search.get('count', 0)}건 수집 "
            f"(fallback_level={cl_search.get('fallback_level')}, "
            f"is_fallback={cl_search.get('is_fallback')})"
        )
        spec_json = payload.user_spec.model_dump_json()
        jd_text = self._hope_career_jd_text(payload)
        _log("[Crew A] Spec_Benchmarker → Gap_Analyzer 순차 실행...")
        benchmark_raw, gap_raw = self._crew.run_benchmark_and_gap({
            "target_company": payload.target_company,
            "target_job": payload.target_job,
            "target_field": payload.target_field,
            "cover_letters_context": format_for_agent(cl_search),
            "jd_context": jd_text,
            "user_spec": spec_json,
            "user_feedback_1": "특이사항 없음",
            "psychological_test": self._psych_json(payload),
        })
        benchmark = cover_letter_service.enrich_benchmark_output(benchmark_raw, cl_search)
        benchmark = sanitize_benchmark_output(benchmark, target_company=company)
        count = cl_search.get("count", 0) or len(cl_search.get("items") or [])
        benchmark.setdefault("source_meta", {})
        benchmark["source_meta"]["cover_letter_count"] = count
        benchmark["source_meta"]["fallback_level"] = cl_search.get("fallback_level")
        benchmark["source_meta"]["is_fallback"] = cl_search.get("is_fallback", False)
        if isinstance(benchmark, dict) and benchmark:
            universal_cache.cache_json("benchmark", bench_key, benchmark)

        gap = self._enrich_gap_output(gap_raw, benchmark, payload.user_spec)
        fb_str = "특이사항 없음"
        gap_key = f"gap::{_h(spec_json[:200])}::{_h(json.dumps(benchmark, ensure_ascii=False)[:200])}::{_h(fb_str)}"
        if isinstance(gap, dict) and gap:
            universal_cache.cache_json("gap", gap_key, gap)
        _log(f"[Crew A] 완료 ✅ ({time.time() - t0:.1f}s)")
        return benchmark, gap

    # ===================================================================
    # [HITL 2단계] 진정성/전문성 갭 진단 (단독 — HITL 재진단용)
    # ===================================================================
    def analyze_gap(self, payload: RoadmapGapRequest) -> dict:
        t0 = time.time()
        spec_json = payload.user_spec.model_dump_json()
        bench_json = json.dumps(payload.benchmark_output, ensure_ascii=False)
        fb_str = payload.user_feedback_1 or "특이사항 없음"
        cache_key = f"gap::{_h(spec_json[:200])}::{_h(bench_json[:200])}::{_h(fb_str)}"
        cached = universal_cache.get_json("gap", cache_key)
        if cached:
            _log(f"[2단계] 캐시 HIT ✅ — LLM 생략 ({time.time() - t0:.2f}s)")
            return cached

        _log("[2단계] Gap_Analyzer_Agent(갭 진단가) 가동 중... (LLM 추론)")
        result = self._crew.run_gap({
            "user_spec": spec_json,
            "benchmark_output": bench_json,
            "user_feedback_1": fb_str,
            "psychological_test": self._psych_json(payload),
            "jd_context": self._hope_career_jd_text(payload),
        })
        result = self._enrich_gap_output(
            result,
            payload.benchmark_output or {},
            payload.user_spec,
        )
        if isinstance(result, dict) and result:
            universal_cache.cache_json("gap", cache_key, result)
        _log(f"[2단계] 완료 ✅ ({time.time() - t0:.1f}s)")
        return result

    # ===================================================================
    # [신규 통합 4단계] 합격자 평균 스펙 벤치마킹
    # ===================================================================
    def analyze_benchmark(self, payload) -> dict:
        from services.cover_letter_service import cover_letter_service, format_for_agent

        t0 = time.time()
        cache_key = f"benchmark::{payload.target_company.strip()}::{payload.target_job.strip()}"
        cached = universal_cache.get_json("benchmark", cache_key)
        if cached:
            _log(f"[벤치마크] 캐시 HIT ✅ — 자소서 수집/LLM 생략 ({time.time() - t0:.2f}s)")
            return cached
        _log("[벤치마크] Rule-based 합격 자소서 수집 (스케일다운) 시작...")
        cl_search = cover_letter_service.search_with_fallback(
            target_field=payload.target_field.strip(),
            target_company=payload.target_company.strip(),
            target_job=payload.target_job.strip(),
        )
        _log(
            f"[벤치마크] 자소서 {cl_search.get('count', 0)}건 수집 "
            f"(fallback_level={cl_search.get('fallback_level')}, "
            f"is_fallback={cl_search.get('is_fallback')})"
        )
        _log("[벤치마크] Spec_Benchmarker_Agent 가동 중...")
        result = self._crew.run_benchmark({
            "target_company": payload.target_company,
            "target_job": payload.target_job,
            "target_field": payload.target_field,
            "cover_letters_context": format_for_agent(cl_search),
            "jd_context": self._hope_career_jd_text(payload),
        })
        result = cover_letter_service.enrich_benchmark_output(result, cl_search)
        result = sanitize_benchmark_output(
            result,
            target_company=payload.target_company.strip(),
        )
        count = cl_search.get("count", 0) or len(cl_search.get("items") or [])
        result.setdefault("source_meta", {})
        result["source_meta"]["cover_letter_count"] = count
        result["source_meta"]["fallback_level"] = cl_search.get("fallback_level")
        result["source_meta"]["is_fallback"] = cl_search.get("is_fallback", False)
        if isinstance(result, dict) and result:
            universal_cache.cache_json("benchmark", cache_key, result)
        _log(f"[벤치마크] 완료 ✅ ({time.time() - t0:.1f}s)")
        return result

    # ===================================================================
    # [최종 3단계] 실시간 소싱 + 액션 로드맵 합성
    # ===================================================================
    def synthesize_final(self, payload: RoadmapFinalRequest) -> RoadmapAnalyzeResponse:
        t0 = time.time()

        keywords = self._gap_keywords(
            payload.confirmed_gap,
            target_company=payload.target_company.strip(),
        )
        _log(f"[3단계] 실시간 외부 소싱 시작 (공모전/부트캠프·훈련/인턴) — 키워드: {keywords}")

        job = payload.target_job.strip()
        field = payload.target_field.strip()
        company = payload.target_company.strip()

        sourced = self._source_layer(keywords, job, field, company)

        _log("[Crew B] Roadmap_Harness → Dashboard_Summarizer 순차 실행... (소싱 반영)")

        roadmap_inputs = {
            "confirmed_gap": json.dumps(payload.confirmed_gap, ensure_ascii=False),
            "benchmark_output": json.dumps(payload.benchmark_output or {}, ensure_ascii=False),
            "user_feedback_2": payload.user_feedback_2 or "특이사항 없음",
            "sources_text": self._sources_text(sourced) or "(실시간 소싱 데이터 없음)",
            "psychological_test": self._psych_json(payload),
            "user_certificates": self._user_certificates_json(payload),
            "user_spec_full": payload.user_spec.model_dump_json(exclude_none=True) if payload.user_spec else "{}",
        }
        from core.models import DashboardSummaryRequest
        dashboard_req = DashboardSummaryRequest(
            target_field=payload.target_field,
            target_company=payload.target_company,
            target_job=payload.target_job,
            user_name=payload.user_spec.basic_info.name if payload.user_spec and payload.user_spec.basic_info else "지원자",
            gap_output=payload.confirmed_gap,
            benchmark_output=payload.benchmark_output,
            roadmap_result={},
            psychological_test=self._resolve_psychological_test(payload),
        )
        dashboard_inputs = self._dashboard_crew_inputs(dashboard_req)

        roadmap_raw, dashboard_raw = self._crew.run_roadmap_and_dashboard(roadmap_inputs, dashboard_inputs)
        resp = self._map_response(
            roadmap_raw, payload.confirmed_gap, sourced, bridge=None,
            psych=self._resolve_psychological_test(payload),
            user_spec=payload.user_spec,
            target_company=payload.target_company.strip(),
            benchmark_output=payload.benchmark_output,
        )
        resp.corporate_analysis_content = None

        dashboard_summary = self._sanitize_dashboard_summary(
            dashboard_raw,
            payload.confirmed_gap,
            roadmap_raw,
            payload.benchmark_output,
        )
        resp.dashboard_summary = dashboard_summary

        _log(f"[Crew B] 완료 ✅ ({time.time() - t0:.1f}s) — 타임라인 {len(resp.timeline)}-Phase 생성 및 대시보드 요약 완료")
        return resp

    # ===================================================================
    # [대시보드 에이전트] PDF 1페이지 커버 요약 생성
    # ===================================================================
    def build_dashboard_summary(self, payload) -> dict:
        """최종 로드맵 전체 데이터를 종합하여 인사팀장 관점 대시보드 요약을 생성."""
        from core.models import DashboardSummaryRequest
        t0 = time.time()
        _log("[대시보드] Dashboard_Summarizer_Agent 가동 중... (LLM 추론)")

        gap_output = payload.gap_output or {}
        benchmark_output = payload.benchmark_output or {}
        roadmap_result = payload.roadmap_result or {}

        phase1_actions: list[str] = []
        for m in roadmap_result.get("timeline") or []:
            if isinstance(m, dict) and int(float(m.get("phase_num", 0))) == 1:
                phase1_actions = [str(a) for a in (m.get("actions") or []) if a]
                break

        inputs = self._dashboard_crew_inputs(payload, phase1_actions=phase1_actions or None)

        result = self._crew.run_dashboard(
            inputs,
            benchmark_result=benchmark_output,
            gap_result=gap_output,
            roadmap_result=roadmap_result,
        )
        result = self._sanitize_dashboard_summary(result, gap_output, roadmap_result, benchmark_output)
        _log(f"[대시보드] 완료 ✅ ({time.time() - t0:.1f}s)")
        return result


    @staticmethod
    def _benchmark_summary_text(benchmark: dict | None) -> str:
        if not benchmark:
            return "(벤치마크 데이터 없음)"
        lines: list[str] = []
        if benchmark.get("average_gpa") is not None:
            lines.append(f"합격자 평균 학점(4.5 만점): {benchmark['average_gpa']}")
        for cert in benchmark.get("common_certificates") or []:
            lines.append(f"공통 자격증: {cert}")
        for lang in benchmark.get("average_language_scores") or []:
            if isinstance(lang, dict):
                lines.append(f"어학: {lang.get('language', '')} {lang.get('score', '')}".strip())
            else:
                lines.append(f"어학: {lang}")
        for act in (benchmark.get("common_activities_and_careers") or [])[:5]:
            if isinstance(act, dict):
                lines.append(
                    f"합격자 활동: {act.get('activity_name', '')} — "
                    f"{str(act.get('description', ''))[:100]}"
                )
            elif act:
                lines.append(f"합격자 활동: {act}")
        if benchmark.get("fallback_message"):
            lines.append(f"참고: {benchmark['fallback_message']}")
        return "\n".join(lines) if lines else "(벤치마크 요약 없음)"

    def _enrich_gap_output(self, gap: dict, benchmark: dict, user_spec) -> dict:
        """벤치마크 대비 결정론적 Gap 보강 — LLM 누락 시 자격증·어학 항목 주입."""
        if not isinstance(gap, dict):
            gap = {}
        report = list(gap.get("gap_analysis_report") or gap.get("gaps") or [])
        seen_certs: set[str] = set()
        seen_langs: set[str] = set()
        for g in report:
            if not isinstance(g, dict):
                continue
            blob = gap_blob(g)
            label = str(g.get("required_criteria") or g.get("keyword") or "").strip()
            if is_certificate_text(blob, target_company="") and not is_language_text(blob, target_company=""):
                key = normalize_cert_key(label or blob)
                if key:
                    seen_certs.add(key)
            elif is_language_text(blob, target_company=""):
                seen_langs.add(extract_language_type(label or blob).lower())

        owned_certs = self._owned_cert_names(user_spec) if user_spec else set()
        for cert in benchmark.get("common_certificates") or []:
            cert_s = str(cert).strip()
            if not cert_s:
                continue
            cert_key = normalize_cert_key(cert_s)
            if cert_key in seen_certs:
                continue
            if any(cert_key and (cert_key in normalize_cert_key(o) or normalize_cert_key(o) in cert_key) for o in owned_certs):
                continue
            report.append({
                "category": "전문성(Professionalism)",
                "required_criteria": cert_s,
                "current_status": "미보유 (합격자 벤치마크 대비)",
                "gap_description": (
                    f"합격자 상위 스펙에 자주 등장하는 '{cert_s}' 자격증이 현재 스펙에 없습니다."
                ),
                "severity_score": 78,
                "keyword": cert_s,
            })
            seen_certs.add(cert_key)

        owned_langs = self._owned_language_scores(user_spec) if user_spec else {}
        for lang_row in benchmark.get("average_language_scores") or []:
            if not isinstance(lang_row, dict):
                continue
            lang_type = str(lang_row.get("language") or "").strip()
            target = str(lang_row.get("score") or "").strip()
            if not lang_type:
                continue
            label = f"{lang_type} {target}".strip()
            lang_key = extract_language_type(label).lower()
            if lang_key in seen_langs:
                continue
            current, status = self._resolve_lang_current(lang_type, owned_langs)
            if status == "달성":
                continue
            report.append({
                "category": "전문성(Professionalism)",
                "required_criteria": label,
                "current_status": current or "없음",
                "gap_description": f"합격자 평균 어학 스펙({label}) 대비 현재 {current or '미보유'} 상태입니다.",
                "severity_score": 72,
                "keyword": lang_type,
            })
            seen_langs.add(lang_key)

        report = dedupe_gap_report(report)
        report.sort(key=lambda x: -(x.get("severity_score") or 0) if isinstance(x, dict) else 0)
        gap["gap_analysis_report"] = report
        if report and gap.get("total_gap_percentage") is None:
            gap["total_gap_percentage"] = round(
                sum(_clamp_int(g.get("severity_score", 50), 50) for g in report) / len(report)
            )
        return gap

    @staticmethod
    def _sanitize_dashboard_summary(
        result: dict,
        gap: dict,
        roadmap: dict,
        benchmark: dict | None,
    ) -> dict:
        """LLM 환각 방지 — gap_top2·이번 달 과제를 실제 조사 데이터로 고정."""
        if not isinstance(result, dict):
            result = {}
        report = sorted(
            gap.get("gap_analysis_report") or [],
            key=lambda x: -(x.get("severity_score") or 0) if isinstance(x, dict) else 0,
        )
        top2: list[str] = []
        for g in report[:2]:
            if not isinstance(g, dict):
                continue
            label = (g.get("required_criteria") or g.get("keyword") or "").strip()
            if label:
                top2.append(label)
        if top2:
            result["gap_top2"] = top2

        tasks: list[str] = []
        for m in roadmap.get("timeline") or []:
            if isinstance(m, dict) and int(float(m.get("phase_num") or 0)) == 1:
                for a in m.get("actions") or []:
                    if a and str(a).strip():
                        tasks.append(str(a).strip())
                for ag in m.get("action_groups") or []:
                    if isinstance(ag, dict):
                        tasks.extend(str(i).strip() for i in (ag.get("items") or []) if i)
        if not tasks and report:
            g0 = report[0]
            kw = (g0.get("keyword") or g0.get("required_criteria") or "").strip()
            if kw:
                tasks.append(f"{kw} 집중 보완 시작")
        if tasks:
            result["current_month_tasks"] = tasks[:3]

        if gap.get("feedback") and len(str(result.get("total_summary") or "")) < 40:
            result["total_summary"] = str(gap["feedback"])[:400]

        bench_line = RoadmapService._benchmark_summary_text(benchmark or {})
        if bench_line and bench_line != "(벤치마크 데이터 없음)" and len(str(result.get("total_summary") or "")) < 80:
            fb = str(gap.get("feedback") or "")
            result["total_summary"] = (fb + " " + bench_line.split("\n")[0]).strip()[:400]

        return result

    def _gap_derived_actions(
        self,
        phase_num: int,
        confirmed_gap: dict | None,
        benchmark: dict | None,
        *,
        target_company: str = "",
    ) -> list[str]:
        """Gap·벤치마크에서 Phase별 구체 액션 추출."""
        actions: list[str] = []
        report = sorted(
            (confirmed_gap or {}).get("gap_analysis_report") or [],
            key=lambda x: -(x.get("severity_score") or 0) if isinstance(x, dict) else 0,
        )
        bench = benchmark or {}

        if phase_num == 1:
            for g in report[:2]:
                blob = gap_blob(g if isinstance(g, dict) else {})
                if is_language_text(blob, target_company=target_company):
                    actions.append(f"{g.get('required_criteria', '어학')} 목표 설정 및 학습 계획")
        elif phase_num == 2:
            for g in report[:4]:
                if not isinstance(g, dict):
                    continue
                blob = gap_blob(g)
                if is_language_text(blob, target_company=target_company):
                    continue
                kw = (g.get("keyword") or g.get("required_criteria") or "").strip()
                if kw:
                    actions.append(f"{kw} 역량 보완 (학습·자격·프로젝트)")
            for cert in (bench.get("common_certificates") or [])[:3]:
                actions.append(f"합격자 공통 자격증 '{cert}' 취득 로드맵 수립")
            for act in (bench.get("common_activities_and_careers") or [])[:2]:
                name = act.get("activity_name") if isinstance(act, dict) else str(act)
                if name:
                    actions.append(f"합격자 유사 활동 벤치마킹: {name}")
        elif phase_num == 3:
            for g in report[:3]:
                if not isinstance(g, dict):
                    continue
                kw = (g.get("keyword") or g.get("required_criteria") or "").strip()
                if kw:
                    actions.append(f"{kw} 실전 검증 — 공모전·프로젝트·부트캠프 참여")
        elif phase_num == 4:
            actions.append(f"{target_company or '목표 기업'} 신입·인턴 공고 지원 및 포트폴리오 정리")
            for g in report[:2]:
                kw = (g.get("keyword") or g.get("required_criteria") or "").strip()
                if kw:
                    actions.append(f"이력서·포트폴리오에 '{kw}' 보완 스토리 반영")

        return actions

    # ===================================================================
    # Tools Layer: 외부 API 병렬 소싱 (장애 격리)
    # ===================================================================
    def _source_layer(self, keywords: list[str], job: str, field: str = "", company: str = "") -> dict:
        keywords = [k for k in keywords if k][:3] or [job]
        primary_kw = " ".join(dict.fromkeys([job] + keywords)).strip()
        contest_activities: list[dict] = []
        internship_activities: list[dict] = []
        worknet_preview = ""

        # ── Rule-based 직접 크롤 (crawler_rules.py 고정 URL) ─────────────
        _log(f"[소싱] Rule-based 크롤 시작 — 키워드: {primary_kw}")
        intern_limit = 12
        intern_search_queries: list[str] = []
        for q in [field, job, f"{field} {job}".strip(), *keywords[:3]]:
            q = (q or "").strip()
            if q and q not in intern_search_queries:
                intern_search_queries.append(q)
        if not intern_search_queries:
            intern_search_queries = [job or field or primary_kw]

        for kw in keywords[:2] or [job]:
            for item in rule_crawler_tool.fetch_contests(keyword=kw, limit_per_site=6):
                entry = {
                    "source_platform": item["source_platform"],
                    "title": item["title"],
                    "link_url": item.get("link_url") or item.get("link"),
                    "keyword_match": kw,
                    "snippet": item.get("snippet", ""),
                }
                if classify_activity_kind(entry) == "contest":
                    contest_activities.append(entry)

        for search_kw in intern_search_queries:
            for item in rule_crawler_tool.fetch_internships(
                keyword=search_kw, field=field, job=job, limit_per_site=intern_limit,
            ):
                entry = {
                    "source_platform": item["source_platform"],
                    "title": item["title"],
                    "link_url": item.get("link_url") or item.get("link"),
                    "keyword_match": search_kw,
                    "snippet": item.get("snippet", ""),
                }
                if classify_activity_kind(entry) == "internship" and is_strict_internship(entry):
                    internship_activities.append(entry)

        # ── Tavily/Serper 폴백 (직접 크롤 결과 부족 시) ─────────────────
        def _linkareer(kw: str):
            search_query = f"{field} {job} {kw} 공모전 대외활동 D-".strip()
            return ("링커리어(Tavily)", kw, tavily_tool.search_linkareer_active(search_query))

        def _saramin_intern(search_q: str):
            return ("사람인", search_q, saramin_tool.execute(search_q))

        def _wanted_intern(search_q: str):
            results = tavily_tool._raw_search(
                f"site:wanted.co.kr/wd {search_q} 인턴", max_results=12,
            )
            jobs = [
                {
                    "title": (r.get("title") or "").strip(),
                    "link": (r.get("url") or "").strip(),
                    "snippet": (r.get("content") or "")[:300],
                }
                for r in (results or [])
                if "wanted.co.kr" in (r.get("url") or "")
            ]
            return ("원티드(Tavily)", search_q, jobs)

        def _intern_fallback_queries() -> list[str]:
            qs: list[str] = []
            for q in [
                f"{field} 인턴십",
                f"{field} {job} 인턴십",
                f"{job} 인턴십",
                *[f"{field} {job} {kw} 인턴십".strip() for kw in keywords[:2]],
            ]:
                q = q.strip()
                if q and q not in qs:
                    qs.append(q)
            return qs

        def _worknet():
            return ("고용24(Work24)", job, worknet_tool.execute(job, search_type="공채속보"))

        need_contest_fallback = len(contest_activities) < 3
        need_intern_fallback = len(internship_activities) < 6

        if need_contest_fallback or need_intern_fallback:
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = []
                if need_contest_fallback:
                    for kw in keywords:
                        futures.append(pool.submit(_linkareer, kw))
                if need_intern_fallback:
                    for search_q in _intern_fallback_queries():
                        futures.append(pool.submit(_saramin_intern, search_q))
                        futures.append(pool.submit(_wanted_intern, search_q))
                futures.append(pool.submit(_worknet))

                for fut in as_completed(futures):
                    try:
                        platform, kw, data = fut.result()
                    except Exception:
                        continue
                    if platform == "고용24(Work24)":
                        worknet_preview = data if isinstance(data, str) else str(data)
                        continue

                    is_intern_platform = platform in ("사람인", "원티드(Tavily)")
                    target_list = internship_activities if is_intern_platform else contest_activities

                    for item in (data or [])[:12]:
                        title = (item.get("title") or "").strip()
                        link = (item.get("link") or "").strip()
                        if not title:
                            continue
                        snippet = item.get("snippet") or ""
                        entry = {
                            "source_platform": platform,
                            "title": title,
                            "link_url": link or None,
                            "keyword_match": kw,
                            "snippet": snippet[:300],
                        }
                        from core.d_day_engine import is_live_item

                        if not is_live_item(entry):
                            continue
                        kind = classify_activity_kind(entry)
                        if is_intern_platform and kind == "internship" and is_strict_internship(entry):
                            target_list.append(entry)
                        elif not is_intern_platform and kind == "contest":
                            target_list.append(entry)

        def _dedupe(items: list[dict]) -> list[dict]:
            seen, out = set(), []
            for a in items:
                key = a["link_url"] or a["title"]
                if key in seen:
                    continue
                seen.add(key)
                out.append(a)
            return out

        contests_raw = filter_activity_dicts(_dedupe(contest_activities), require_active_signal=False)
        interns_raw = filter_activity_dicts(_dedupe(internship_activities), require_active_signal=False)

        rec_ctx = UserRecommendContext(job=job, field=field, company=company)
        _log(f"[소싱] 고용24 훈련과정 검색(병렬) — 분야:{field} 직무:{job}")
        _train_pool = ThreadPoolExecutor(max_workers=1)
        _train_future = _train_pool.submit(
            training_search_service.search_as_activities, field, job, top_n=6,
        )
        contest_result = live_activity_service.process_pool(
            contests_raw, rec_ctx, kind="공모전",
        )
        intern_result = live_activity_service.process_pool(
            interns_raw, rec_ctx, kind="인턴", min_required=5,
        )

        # 규칙 3: D+ Drop 후 live 부족 시 직무→분야 키워드로 추가 수색
        def _refill_live(
            current: list[dict],
            result: dict,
            *,
            classify_kind: str,
            pool_kind: str,
            fetch_fn,
            strict_intern: bool = False,
        ) -> tuple[list[dict], dict]:
            meta = result.get("d_day_meta") or {}
            min_target = 6 if strict_intern else 3
            if len(current) >= min_target and not meta.get("needs_fallback"):
                return current, result
            seen = {a.get("link_url") or a.get("title") for a in current}
            extra: list[dict] = []
            refill_queries = [field, job, f"{field} {job}".strip(), *keywords[:2]]
            refill_queries = [q.strip() for q in refill_queries if (q or "").strip()]
            for kw in refill_queries or [job]:
                for item in fetch_fn(keyword=kw, limit_per_site=12):
                    entry = {
                        "source_platform": item["source_platform"],
                        "title": item["title"],
                        "link_url": item.get("link_url") or item.get("link"),
                        "keyword_match": kw,
                        "snippet": item.get("snippet", ""),
                    }
                    if classify_activity_kind(entry) != classify_kind:
                        continue
                    if strict_intern and not is_strict_internship(entry):
                        continue
                    key = entry.get("link_url") or entry.get("title")
                    if key in seen:
                        continue
                    seen.add(key)
                    extra.append(entry)
            if not extra:
                return current, result
            merged = _dedupe((current or []) + filter_activity_dicts(extra, require_active_signal=False))
            refreshed = live_activity_service.process_pool(merged, rec_ctx, kind=pool_kind)
            items = refreshed["items"]
            if strict_intern:
                items = [i for i in items if is_strict_internship(i)]
            return items, refreshed

        def _fetch_interns_refill(*, keyword: str = "", limit_per_site: int = 6, **_kwargs):
            return rule_crawler_tool.fetch_internships(
                keyword=keyword, field=field, job=job, limit_per_site=limit_per_site,
            )

        contests, contest_result = _refill_live(
            contest_result["items"], contest_result,
            classify_kind="contest", pool_kind="공모전",
            fetch_fn=rule_crawler_tool.fetch_contests,
        )
        interns, intern_result = _refill_live(
            intern_result["items"], intern_result,
            classify_kind="internship", pool_kind="인턴",
            fetch_fn=_fetch_interns_refill,
            strict_intern=True,
        )
        interns = [i for i in interns if is_strict_internship(i)]
        interns.sort(
            key=lambda x: -float(x.get("final_matching_score") or x.get("matching_score") or 0),
        )

        # 고용24 훈련: refill과 동시에 백그라운드 검색 (이미 시작됐으면 result만)
        training_raw = _train_future.result()
        _train_pool.shutdown(wait=False)

        training_result = live_activity_service.process_pool(
            training_raw, rec_ctx, kind="부트캠프", min_required=1,
        )
        trainings = training_result["items"]

        d_dropped = (
            (contest_result.get("d_day_meta") or {}).get("dropped_expired", 0)
            + (intern_result.get("d_day_meta") or {}).get("dropped_expired", 0)
            + (training_result.get("d_day_meta") or {}).get("dropped_expired", 0)
        )
        _log(
            f"[소싱] 라이브 공모전 {len(contests)}건 · 부트캠프/훈련 {len(trainings)}건 · 인턴 {len(interns)}건 "
            f"(D+ 제외 {d_dropped}건 · 임박순 정렬)"
        )
        return {
            "contest_activities": contests[:8],
            "training_activities": trainings[:8],
            "internship_activities": interns[:12],
            "activities": (contests + trainings + interns)[:12],
            "worknet_preview": worknet_preview,
            "recommendation_context": {
                "focus_priority": ["job_role", "industry_domain", "company_match"],
                "is_lock_in_prevented": True,
                "d_day_filtered": True,
            },
            "d_day_meta": {
                "contest": contest_result.get("d_day_meta"),
                "training": training_result.get("d_day_meta"),
                "internship": intern_result.get("d_day_meta"),
                "dropped_expired_total": d_dropped,
            },
        }

    def _gap_keywords(self, confirmed_gap: dict, *, target_company: str = "") -> list[str]:
        """확정 Gap 리포트에서 보완 검색 키워드 추출 (어학·기업 맥락 제외)."""
        kws: list[str] = []
        report = confirmed_gap.get("gap_analysis_report") or confirmed_gap.get("gaps") or []
        for g in report:
            if not isinstance(g, dict):
                continue
            blob = gap_blob(g)
            from core.spec_classifier import classify_credential_text

            if is_language_text(blob, target_company=target_company):
                continue
            if classify_credential_text(blob, target_company=target_company) == "CORPORATE_EXPERIENCE":
                continue
            kw = g.get("keyword") or g.get("required_criteria") or g.get("category")
            if kw:
                kws.append(str(kw).strip())
        return kws

    def _sources_text(self, sourced: dict) -> str:
        lines = ["[Phase 3 전용 — 공모전/프로젝트 + 부트캠프/훈련과정]"]
        contests = sourced.get("contest_activities") or []
        if contests:
            lines.append("▶ 공모전/프로젝트")
            for a in contests[:4]:
                url = a.get("link_url") or "URL 없음"
                label = a.get("d_day_label") or ""
                date_disp = a.get("deadline_display") or ""
                tag = f" [{label}" + (f" · {date_disp}" if date_disp else "") + "]" if label or date_disp else ""
                lines.append(f"- [{a['source_platform']}] (Gap:{a['keyword_match']}) {a['title']}{tag} ({url})")
        else:
            lines.append("▶ 공모전/프로젝트: (수집 없음)")

        trainings = sourced.get("training_activities") or []
        if trainings:
            lines.append("▶ 부트캠프/훈련과정 (고용24)")
            for a in trainings[:4]:
                url = a.get("link_url") or "URL 없음"
                label = a.get("d_day_label") or ""
                date_disp = a.get("deadline_display") or ""
                tag = f" [{label}" + (f" · {date_disp}" if date_disp else "") + "]" if label or date_disp else ""
                lines.append(f"- [{a['source_platform']}] (분야·직무:{a['keyword_match']}) {a['title']}{tag} ({url})")
        else:
            lines.append("▶ 부트캠프/훈련과정: (수집 없음)")

        lines.append("\n[Phase 4 전용 — 인턴십 공고]")
        interns = sourced.get("internship_activities") or []
        if interns:
            for a in interns[:4]:
                url = a.get("link_url") or "URL 없음"
                label = a.get("d_day_label") or ""
                date_disp = a.get("deadline_display") or ""
                tag = f" [{label}" + (f" · {date_disp}" if date_disp else "") + "]" if label or date_disp else ""
                lines.append(f"- [{a['source_platform']}] (Gap:{a['keyword_match']}) {a['title']}{tag} ({url})")
        else:
            lines.append("- (수집된 인턴 공고 없음)")

        preview = sourced.get("worknet_preview", "")
        if preview:
            lines.append("\n[고용24 공채속보 원문 미리보기]\n" + preview[:600])
        return "\n".join(lines)

    # ===================================================================
    # dict → Pydantic 매핑 (안전 폴백 포함)
    # ===================================================================
    def _map_gap_report(self, raw: dict) -> list[GapItem]:
        out: list[GapItem] = []
        for g in raw.get("gap_analysis_report") or []:
            if not isinstance(g, dict):
                continue
            out.append(GapItem(
                category=str(g.get("category", "전문성(Professionalism)")),
                required_criteria=str(g.get("required_criteria", "")),
                current_status=str(g.get("current_status", "")),
                gap_description=str(g.get("gap_description", g.get("feedback", ""))),
                severity_score=_clamp_int(g.get("severity_score", 50), 50),
            ))
        return out

    @staticmethod
    def _activity_timeline_kwargs(a: dict) -> dict:
        """D-Day 라벨 + 실제 마감일 세트 (API·UI 공통)."""
        from core.d_day_engine import annotate_d_day

        ann = annotate_d_day(a)
        deadline = ann.get("deadline") or ann.get("deadline_date")
        return {
            "d_day_label": str(ann.get("d_day_label") or ""),
            "d_day_status": str(ann.get("d_day_status") or ""),
            "deadline": deadline,
            "deadline_display": str(ann.get("deadline_display") or ""),
            "days_remaining": ann.get("days_remaining"),
            "is_live": bool(ann.get("is_live", True)),
        }

    def _map_activities(self, raw_list, sourced: dict) -> list[SourcedActivity]:
        acts: list[SourcedActivity] = []
        for a in filter_source_refs(raw_list or []):
            title = str(a.get("title", "")).strip()
            acts.append(SourcedActivity(
                source_platform=str(a.get("source_platform", "링커리어(Tavily)")),
                title=title,
                link_url=a.get("link_url") or None,
                keyword_match=str(a.get("keyword_match", "")),
                **self._activity_timeline_kwargs(a),
            ))
        return acts

    @staticmethod
    def _user_certificates_json(payload: RoadmapCriteriaRequest) -> str:
        certs = payload.user_spec.certificates or []
        if not certs:
            return "(등록된 자격증 없음)"
        lines = [f"- {c.name} ({c.issuer})" for c in certs if c.name]
        return "\n".join(lines) if lines else "(등록된 자격증 없음)"

    @staticmethod
    def _owned_cert_names(user_spec) -> set[str]:
        names: set[str] = set()
        for c in user_spec.certificates or []:
            name = (c.name or "").strip().lower()
            if name:
                names.add(name)
        return names

    @staticmethod
    def _is_cert_text(text: str, *, target_company: str = "") -> bool:
        if is_language_text(text, target_company=target_company):
            return False
        return is_certificate_text(text, target_company=target_company)

    @staticmethod
    def _owned_language_scores(user_spec) -> dict[str, str]:
        owned: dict[str, str] = {}
        for lang in user_spec.languages or []:
            key = (lang.language_type or "").strip().lower()
            if key:
                owned[key] = str(lang.score or "").strip()
        return owned

    @staticmethod
    def _resolve_lang_current(lang_type: str, owned: dict[str, str]) -> tuple[str, str]:
        """user_spec.languages와 LLM 어학 요건 매칭 → (current_score, status)."""
        lt = (lang_type or "").strip().lower()
        if not lt:
            return "없음", "미달"
        for key, score in owned.items():
            if key in lt or lt in key:
                return score or "없음", "달성"
            if key.startswith("toeic") and "toeic" in lt:
                return score or "없음", "달성"
            if key.startswith("opic") and "opic" in lt:
                return score or "없음", "달성"
        return "없음", "미달"

    def _map_required_language_scores(
        self,
        roadmap_raw: dict,
        gap_items: list[GapItem],
        user_spec,
        *,
        target_company: str = "",
    ) -> list:
        from core.models import RequiredLanguageScore
        from core.spec_classifier import extract_language_type

        owned = self._owned_language_scores(user_spec) if user_spec else {}
        out: list[RequiredLanguageScore] = []
        seen: set[str] = set()

        def _add(item: dict) -> None:
            lang_type = str(item.get("language_type") or item.get("language") or "").strip()
            if not lang_type:
                return
            if not is_language_text(lang_type, target_company=target_company):
                return
            key = lang_type.lower()
            if key in seen:
                return
            seen.add(key)
            target = str(item.get("target_score") or item.get("score") or "").strip()
            current = str(item.get("current_score") or "").strip()
            status = str(item.get("status") or "").strip()
            if not current or current == "없음":
                current, status = self._resolve_lang_current(lang_type, owned)
            elif status not in ("달성", "미달"):
                _, status = self._resolve_lang_current(lang_type, owned)
            out.append(RequiredLanguageScore(
                language_type=lang_type,
                target_score=target,
                current_score=current or "없음",
                status=status if status in ("달성", "미달") else "미달",
            ))

        for item in roadmap_raw.get("required_language_scores") or []:
            if isinstance(item, dict):
                _add(item)

        if not out:
            for g in gap_items:
                blob = gap_blob(g.model_dump())
                if not is_language_text(blob, target_company=target_company):
                    continue
                lang_type = extract_language_type(g.required_criteria or blob)
                _add({
                    "language_type": lang_type,
                    "target_score": g.required_criteria,
                    "current_score": g.current_status,
                })

        return out

    @classmethod
    def _cert_status(cls, name: str, owned: set[str]) -> str:
        key = name.strip().lower()
        if not key:
            return "취득 필요"
        for o in owned:
            if o in key or key in o:
                return "보유"
        return "취득 필요"

    def _map_required_certifications(
        self,
        roadmap_raw: dict,
        gap_items: list[GapItem],
        user_spec,
        *,
        target_company: str = "",
    ) -> list[RequiredCertification]:
        owned = self._owned_cert_names(user_spec)
        out: list[RequiredCertification] = []
        seen: set[str] = set()

        def _add(item: dict) -> None:
            name = str(item.get("name") or item.get("certification") or "").strip()
            if not name:
                return
            if is_language_text(name, target_company=target_company):
                return
            key = normalize_cert_key(name)
            if not key or key in seen:
                return
            seen.add(key)
            status = str(item.get("status") or self._cert_status(name, owned))
            if status not in ("보유", "취득 필요"):
                status = self._cert_status(name, owned)
            out.append(RequiredCertification(
                name=name,
                issuer=str(item.get("issuer") or ""),
                priority=str(item.get("priority") or "권장"),
                target_phase=_clamp_int(item.get("target_phase"), 3) or 3,
                reason=str(item.get("reason") or item.get("gap_description") or ""),
                status=status,
            ))

        for item in roadmap_raw.get("required_certifications") or []:
            if isinstance(item, dict):
                _add(item)
            elif isinstance(item, str) and item.strip():
                _add({"name": item.strip()})

        for m in roadmap_raw.get("timeline") or []:
            if not isinstance(m, dict):
                continue
            phase = _clamp_int(m.get("phase_num"), 3) or 3
            for cert_name in m.get("required_certifications") or []:
                label = self._cert_label(cert_name)
                if label:
                    _add({"name": label, "target_phase": phase})

        if not out:
            for g in gap_items:
                blob = gap_blob(g.model_dump())
                if not self._is_cert_text(blob, target_company=target_company):
                    continue
                name = g.required_criteria.strip()
                if len(name) < 2:
                    continue
                _add({
                    "name": name,
                    "reason": g.gap_description,
                    "priority": "필수" if g.severity_score >= 70 else "권장",
                    "target_phase": 3,
                })

        out.sort(key=lambda c: (0 if c.status == "취득 필요" else 1, -{"필수": 3, "권장": 2, "우대": 1}.get(c.priority, 0)))
        return out

    @staticmethod
    def _cert_label(item) -> str:
        """timeline required_certifications 항목 → 자격증명 문자열만 추출."""
        if isinstance(item, dict):
            return str(item.get("name") or item.get("certification") or "").strip()
        if not isinstance(item, str):
            item = str(item)
        s = item.strip()
        if not s:
            return ""
        if s.startswith("{") and "name" in s:
            try:
                parsed = json.loads(s.replace("'", '"'))
                if isinstance(parsed, dict):
                    return str(parsed.get("name") or "").strip()
            except Exception:
                pass
            try:
                import ast
                parsed = ast.literal_eval(s)
                if isinstance(parsed, dict):
                    return str(parsed.get("name") or "").strip()
            except Exception:
                pass
            m = re.search(r"""['"]name['"]\s*:\s*['"]([^'"]+)['"]""", s)
            if m:
                return m.group(1).strip()
        return s

    def _map_source_refs(self, raw_list, *, strict: bool = True) -> list[SourceRef]:
        """로드맵 sources — D+ Hard Rule 재검증 (strict 무관 항상 적용)."""
        refs: list[SourceRef] = []
        items = filter_source_refs(raw_list or [])
        for a in items:
            if not isinstance(a, dict):
                continue
            title = str(a.get("title", "")).strip()
            if not title:
                continue
            refs.append(SourceRef(
                source_platform=str(a.get("source_platform", "링커리어(Tavily)")),
                title=title,
                link_url=a.get("link_url") or None,
                keyword_match=str(a.get("keyword_match", "")),
                **self._activity_timeline_kwargs(a),
            ))
        return refs

    def _sourced_pool(self, sourced: dict, kind: str) -> list[SourceRef]:
        key_map = {
            "contest": "contest_activities",
            "training": "training_activities",
            "internship": "internship_activities",
        }
        key = key_map.get(kind, "contest_activities")
        return self._map_source_refs(sourced.get(key) or [], strict=False)

    def _sources_for_phase(
        self,
        raw_sources: list,
        phase_num: int,
        sourced: dict,
    ) -> list[SourceRef]:
        """Phase별 활동 유형 강제 분배 — P3=공모전+부트캠프, P4=인턴만."""
        if phase_num not in (3, 4):
            return self._map_source_refs(raw_sources or [])

        mapped = self._map_source_refs(raw_sources or [])

        if phase_num == 3:
            want_kinds = {"contest", "training"}
            pool = self._sourced_pool(sourced, "contest") + self._sourced_pool(sourced, "training")
            correct = [
                s for s in mapped
                if classify_activity_kind(s.model_dump()) in want_kinds
            ]
        else:
            pool = [
                s for s in self._sourced_pool(sourced, "internship")
                if is_strict_internship(s.model_dump())
            ]
            correct = [
                s for s in mapped
                if is_strict_internship(s.model_dump())
                and classify_activity_kind(s.model_dump()) not in {"contest", "training"}
            ]

        seen: set[str] = set()
        out: list[SourceRef] = []
        for s in correct + pool:
            key = s.link_url or s.title
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= 12:
                break
        # LLM이 sources를 비워도 소싱 풀에서 Phase별 최소 건수 보장
        min_phase_sources = 6 if phase_num == 4 else 2
        if len(out) < min_phase_sources and pool:
            for s in pool:
                key = s.link_url or s.title
                if key in seen:
                    continue
                seen.add(key)
                out.append(s)
                if len(out) >= min_phase_sources:
                    break
        return out

    def _parse_raw_phases(self, roadmap_raw: dict) -> list[dict]:
        """LLM timeline 또는 legacy structured_roadmap 파싱."""
        items: list[dict] = []
        for s in roadmap_raw.get("timeline") or []:
            if isinstance(s, dict):
                items.append(s)
        if items:
            return items
        for s in roadmap_raw.get("structured_roadmap") or []:
            if not isinstance(s, dict):
                continue
            phase_str = str(s.get("phase", ""))
            num_m = re.search(r"Phase\s*(\d+)", phase_str, re.I)
            items.append({
                "phase_num": int(num_m.group(1)) if num_m else len(items) + 1,
                "phase_title": s.get("phase_title") or phase_str,
                "period": s.get("period") or "",
                "narrative_bridge_directive": s.get("narrative_bridge_directive") or "",
                "actions": s.get("actions") or s.get("action_items") or [],
                "sources": s.get("sources") or s.get("recommended_activities") or [],
                "expected_outcome": s.get("expected_outcome") or "",
            })
        return items

    def _normalize_timeline(
        self,
        roadmap_raw: dict,
        bridge: dict | None,
        sourced: dict,
        psych: dict | None,
        confirmed_gap: dict | None = None,
        benchmark: dict | None = None,
        *,
        target_company: str = "",
    ) -> list[RoadmapMilestone]:
        parsed = self._parse_raw_phases(roadmap_raw)
        by_num = {}
        for i, p in enumerate(parsed):
            num = _clamp_int(p.get("phase_num"), i + 1)
            if num < 1 or num > 4:
                num = min(4, i + 1)
            by_num[num] = p

        constraints = (bridge or {}).get("gap_to_activity_constraints") or []
        buildup = (bridge or {}).get("four_buildup_plan") or []

        milestones: list[RoadmapMilestone] = []
        for spec in PHASE_SPECS:
            n = spec["phase_num"]
            raw = by_num.get(n, {})
            idx = n - 1

            directive = str(
                raw.get("narrative_bridge_directive")
                or raw.get("narrative_directive")
                or ""
            ).strip()
            if not directive and constraints and idx < len(constraints):
                c = constraints[idx]
                directive = " · ".join(filter(None, [
                    c.get("resume_narrative_rule"),
                    c.get("sourcing_constraint"),
                    c.get("missing_narrative"),
                ]))
            if not directive and buildup and idx < len(buildup):
                b = buildup[idx]
                directive = b if isinstance(b, str) else str(b.get("label") or b.get("step") or "")
            if n == 1 and not directive:
                directive = (bridge or {}).get("storyline") or (bridge or {}).get("summary") or ""
                if psych:
                    code = (psych.get("interest") or {}).get("riasec_code", "")
                    directive = (directive + f" Holland {code}·Big5 정합 서사").strip()

            actions = [str(x) for x in (raw.get("actions") or raw.get("action_items") or []) if x]
            derived = self._gap_derived_actions(
                n, confirmed_gap, benchmark, target_company=target_company,
            )
            actions = list(dict.fromkeys(actions + derived))[:10]

            action_groups_raw = raw.get("action_groups") or []
            action_groups = []
            from core.models import ActionGroup
            for ag in action_groups_raw:
                if isinstance(ag, dict) and ag.get("category"):
                    action_groups.append(ActionGroup(
                        category=str(ag.get("category")),
                        items=[str(x) for x in ag.get("items", []) if x]
                    ))

            sources = self._sources_for_phase(
                raw.get("sources") or raw.get("recommended_activities"),
                n,
                sourced,
            )

            period = str(raw.get("period") or spec["period"])
            title = str(raw.get("phase_title") or spec["phase_title"])
            outcome = str(raw.get("expected_outcome") or "")
            phase_certs = []
            for x in raw.get("required_certifications") or []:
                label = self._cert_label(x)
                if label and label not in phase_certs:
                    phase_certs.append(label)

            milestones.append(RoadmapMilestone(
                phase_num=n,
                phase_title=title,
                period=period,
                narrative_bridge_directive=directive,
                actions=actions,
                action_groups=action_groups,
                sources=sources,
                expected_outcome=outcome,
                required_certifications=phase_certs,
            ))
        return milestones

    def _timeline_to_steps(self, timeline: list[RoadmapMilestone]) -> list[RoadmapStep]:
        steps: list[RoadmapStep] = []
        for m in timeline:
            steps.append(RoadmapStep(
                phase=f"Phase {m.phase_num}: {m.phase_title} ({m.period})",
                phase_title=m.phase_title,
                action_items=m.actions,
                action_groups=m.action_groups,
                recommended_activities=[
                    SourcedActivity(
                        source_platform=s.source_platform,
                        title=s.title,
                        link_url=s.link_url,
                        keyword_match=s.keyword_match,
                        d_day_label=s.d_day_label,
                        d_day_status=s.d_day_status,
                        deadline=s.deadline,
                        deadline_display=s.deadline_display,
                        days_remaining=s.days_remaining,
                        is_live=s.is_live,
                    )
                    for s in m.sources
                ],
                expected_outcome=m.expected_outcome,
                narrative_bridge_directive=m.narrative_bridge_directive,
            ))
        return steps

    def _attach_certs_to_timeline(
        self,
        timeline: list[RoadmapMilestone],
        required_certs: list[RequiredCertification],
    ) -> list[RoadmapMilestone]:
        by_phase: dict[int, list[str]] = {}
        for c in required_certs:
            if c.status != "취득 필요":
                continue
            by_phase.setdefault(c.target_phase, [])
            if c.name not in by_phase[c.target_phase]:
                by_phase[c.target_phase].append(c.name)
        updated: list[RoadmapMilestone] = []
        for m in timeline:
            clean = [self._cert_label(x) for x in (m.required_certifications or [])]
            clean = [x for x in clean if x]
            merged = list(dict.fromkeys(clean + by_phase.get(m.phase_num, [])))
            updated.append(m.model_copy(update={"required_certifications": merged}))
        return updated

    def _map_response(
        self, roadmap_raw: dict, confirmed_gap: dict, sourced: dict, bridge: dict | None = None,
        psych: dict | None = None, user_spec=None, *, target_company: str = "",
        benchmark_output: dict | None = None,
    ) -> RoadmapAnalyzeResponse:
        # gap_analysis_report: 로드맵 산출물 우선, 없으면 확정 Gap 재사용
        gap_items = self._map_gap_report(roadmap_raw)
        if not gap_items:
            gap_items = self._map_gap_report(confirmed_gap)

        total = roadmap_raw.get("total_gap_percentage")
        if total is None:
            total = confirmed_gap.get("total_gap_percentage", 0)

        timeline = self._normalize_timeline(
            roadmap_raw, bridge, sourced, psych,
            confirmed_gap=confirmed_gap,
            benchmark=benchmark_output,
            target_company=target_company,
        )
        required_certs = (
            self._map_required_certifications(
                roadmap_raw, gap_items, user_spec, target_company=target_company,
            )
            if user_spec else []
        )
        timeline = self._attach_certs_to_timeline(timeline, required_certs)
        steps = self._timeline_to_steps(timeline)

        lang_scores = (
            self._map_required_language_scores(
                roadmap_raw, gap_items, user_spec, target_company=target_company,
            )
            if user_spec else []
        )

        return RoadmapAnalyzeResponse(
            success=True,
            total_gap_percentage=_clamp_float(total),
            gap_analysis_report=gap_items,
            timeline=timeline,
            structured_roadmap=steps,
            required_certifications=required_certs,
            required_language_scores=lang_scores,
            narrative_bridge_report=bridge or None,
        )


def normalize_roadmap_pdf_payload(raw: dict) -> dict:
    """프론트 finalData 스냅샷 → PDF 생성용 평탄 dict (검증 실패 방지)."""
    if not isinstance(raw, dict):
        return {}
    rm = dict(raw)
    rm["success"] = bool(rm.get("success", True))
    try:
        rm["total_gap_percentage"] = float(rm.get("total_gap_percentage") or 0)
    except (TypeError, ValueError):
        rm["total_gap_percentage"] = 0.0

    gaps: list[dict] = []
    for g in rm.get("gap_analysis_report") or []:
        if not isinstance(g, dict):
            continue
        try:
            sev = int(float(g.get("severity_score") or 50))
        except (TypeError, ValueError):
            sev = 50
        gaps.append({
            "category": str(g.get("category") or "전문성(Professionalism)"),
            "required_criteria": str(g.get("required_criteria") or ""),
            "current_status": str(g.get("current_status") or ""),
            "gap_description": str(g.get("gap_description") or g.get("feedback") or ""),
            "severity_score": max(0, min(100, sev)),
        })
    rm["gap_analysis_report"] = gaps

    certs: list[dict] = []
    for c in rm.get("required_certifications") or []:
        if isinstance(c, dict):
            name = RoadmapService._cert_label(c) or str(c.get("name") or "").strip()
            if not name:
                continue
            try:
                tp = int(float(c.get("target_phase") or 3))
            except (TypeError, ValueError):
                tp = 3
            certs.append({
                "name": name,
                "issuer": str(c.get("issuer") or ""),
                "priority": str(c.get("priority") or "권장"),
                "target_phase": max(1, min(4, tp)),
                "reason": str(c.get("reason") or ""),
                "status": str(c.get("status") or "취득 필요"),
            })
        elif isinstance(c, str) and c.strip():
            certs.append({
                "name": RoadmapService._cert_label(c),
                "issuer": "",
                "priority": "권장",
                "target_phase": 3,
                "reason": "",
                "status": "취득 필요",
            })
    rm["required_certifications"] = certs

    timeline: list[dict] = []
    for m in rm.get("timeline") or []:
        if not isinstance(m, dict):
            continue
        try:
            pnum = int(float(m.get("phase_num") or len(timeline) + 1))
        except (TypeError, ValueError):
            pnum = len(timeline) + 1
        pnum = max(1, min(4, pnum))
        cert_labels: list[str] = []
        for x in m.get("required_certifications") or []:
            lbl = RoadmapService._cert_label(x)
            if lbl and lbl not in cert_labels:
                cert_labels.append(lbl)
        actions = [str(a) for a in (m.get("actions") or m.get("action_items") or []) if a]
        
        action_groups_raw = m.get("action_groups") or []
        action_groups_dict = []
        for ag in action_groups_raw:
            if isinstance(ag, dict) and ag.get("category"):
                action_groups_dict.append({
                    "category": str(ag.get("category")),
                    "items": [str(x) for x in ag.get("items", []) if x]
                })
        
        sources: list[dict] = []
        for s in m.get("sources") or m.get("recommended_activities") or []:
            if not isinstance(s, dict):
                continue
            title = str(s.get("title") or "").strip()
            if not title:
                continue
            sources.append({
                "source_platform": str(s.get("source_platform") or ""),
                "title": title,
                "link_url": s.get("link_url"),
                "keyword_match": str(s.get("keyword_match") or ""),
                "d_day_label": str(s.get("d_day_label") or ""),
                "d_day_status": str(s.get("d_day_status") or ""),
                "deadline": s.get("deadline"),
                "deadline_display": str(s.get("deadline_display") or ""),
                "days_remaining": s.get("days_remaining"),
                "is_live": bool(s.get("is_live", True)),
            })
        timeline.append({
            "phase_num": pnum,
            "phase_title": str(m.get("phase_title") or f"Phase {pnum}"),
            "period": str(m.get("period") or ""),
            "narrative_bridge_directive": str(m.get("narrative_bridge_directive") or ""),
            "actions": actions,
            "action_groups": action_groups_dict,
            "sources": sources,
            "expected_outcome": str(m.get("expected_outcome") or ""),
            "required_certifications": cert_labels,
        })
    rm["timeline"] = timeline
    
    lang_scores = []
    for ls in raw.get("required_language_scores") or []:
        if isinstance(ls, dict):
            lang_scores.append({
                "language_type": str(ls.get("language_type") or ""),
                "target_score": str(ls.get("target_score") or ""),
                "current_score": str(ls.get("current_score") or "없음"),
                "status": str(ls.get("status") or "미달"),
            })
    rm["required_language_scores"] = lang_scores

    bridge = rm.get("narrative_bridge_report")
    rm["narrative_bridge_report"] = bridge if isinstance(bridge, dict) else {}
    
    dashboard_summary = rm.get("dashboard_summary")
    if dashboard_summary and isinstance(dashboard_summary, dict):
        rm["dashboard_summary"] = dashboard_summary
        
    return rm


# 싱글톤 인스턴스
roadmap_service = RoadmapService()
