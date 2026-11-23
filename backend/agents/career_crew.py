"""
[CrewAI Multi-Agent Layer] LinkareerCareerCrew
선언형(YAML) 4대 로드맵 에이전트 + JD 전용 1종.

순차 Crew (Process.sequential):
  Crew A: Spec_Benchmarker → Gap_Analyzer        (/benchmark, 크롤 직후)
  [HITL + Python 소싱]
  Crew B: Roadmap_Harness → Dashboard_Summarizer (/final)

JD_Structural_Analyzer 는 희망 직무 캐시 저장 시에만 단독 실행.
"""
from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, task

from datetime import date

from core.config import settings
from core.utils import safe_parse_json
from agents.tools import text_cleaner_tool, pydantic_schema_validator, playwright_scraper_tool, tavily_search_tool, advanced_platform_scraper_tool, cover_letter_search_tool


def _crew_date_inputs(extra: dict | None = None) -> dict:
    """모든 CrewAI 태스크에 주입할 현재 날짜 컨텍스트."""
    today = date.today()
    base = {
        "current_date": today.isoformat(),
        "current_year": str(today.year),
        "past_year_example": str(today.year - 1),
    }
    if extra:
        base.update(extra)
    return base


@CrewBase
class LinkareerCareerCrew:
    """
    핵심 3+1 에이전트(Spec_Benchmarker, Gap_Analyzer, Roadmap_Harness, Dashboard_Summarizer)를
    YAML 선언으로 구성하는 CrewAI 크루. 싱글톤으로 사용.
    """

    import os
    agents_config = os.path.join(os.path.dirname(__file__), "config", "agents.yaml")
    tasks_config = os.path.join(os.path.dirname(__file__), "config", "tasks.yaml")

    def __init__(self) -> None:
        self._llm = LLM(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=0.3,
        )
        self.VERBOSE = settings.CREW_VERBOSE

    @agent
    def gap_analyzer(self) -> Agent:
        return Agent(config=self.agents_config["gap_analyzer"], llm=self._llm, verbose=self.VERBOSE)

    @agent
    def roadmap_harness(self) -> Agent:
        return Agent(config=self.agents_config["roadmap_harness"], llm=self._llm, verbose=self.VERBOSE)

    @agent
    def dashboard_summarizer(self) -> Agent:
        return Agent(config=self.agents_config["dashboard_summarizer"], llm=self._llm, verbose=self.VERBOSE)

    @agent
    def jd_structural_analyzer(self) -> Agent:
        return Agent(
            config=self.agents_config["jd_structural_analyzer"],
            llm=self._llm,
            verbose=self.VERBOSE,
            tools=[text_cleaner_tool, pydantic_schema_validator, playwright_scraper_tool],
            max_iter=5,
        )

    @agent
    def spec_benchmarker(self) -> Agent:
        return Agent(
            config=self.agents_config["spec_benchmarker"],
            llm=self._llm,
            verbose=self.VERBOSE,
            tools=[cover_letter_search_tool, tavily_search_tool, advanced_platform_scraper_tool, pydantic_schema_validator]
        )

    @task
    def diagnosis_spec_gap(self) -> Task:
        return Task(config=self.tasks_config["diagnosis_spec_gap"])

    @task
    def synthesize_action_roadmap(self) -> Task:
        return Task(config=self.tasks_config["synthesize_action_roadmap"])

    @task
    def summarize_dashboard(self) -> Task:
        return Task(config=self.tasks_config["summarize_dashboard"])

    @task
    def structuralize_jd(self) -> Task:
        return Task(config=self.tasks_config["structuralize_jd"])

    @task
    def benchmark_accepted_specs(self) -> Task:
        return Task(config=self.tasks_config["benchmark_accepted_specs"])

    def _make_task(self, task_key: str, agent_obj: Agent, *, context: list | None = None) -> Task:
        cfg = self.tasks_config[task_key]
        return Task(
            description=cfg["description"],
            expected_output=cfg["expected_output"],
            agent=agent_obj,
            human_input=False,
            context=context or [],
        )

    def _crew_task_raws(self, result) -> list[str]:
        if hasattr(result, "tasks_output") and result.tasks_output:
            return [str(getattr(t, "raw", "") or "") for t in result.tasks_output]
        return [str(getattr(result, "raw", result) or "")]

    def _run_sequential_crew(self, agents: list[Agent], tasks: list[Task], inputs: dict):
        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            memory=False,
            verbose=self.VERBOSE,
        ).kickoff(inputs=_crew_date_inputs(inputs))

    def _run_single(self, agent_obj: Agent, task_key: str, inputs: dict) -> str:
        single = self._make_task(task_key, agent_obj)
        result = self._run_sequential_crew([agent_obj], [single], inputs)
        raws = self._crew_task_raws(result)
        return raws[0] if raws else ""

    def run_benchmark_and_gap(self, inputs: dict) -> tuple[dict, dict]:
        """Crew A: Spec_Benchmarker → Gap_Analyzer (순차 1회 kickoff)."""
        bench_agent = self.spec_benchmarker()
        gap_agent = self.gap_analyzer()
        bench_task = self._make_task("benchmark_accepted_specs", bench_agent)
        gap_task = self._make_task("diagnosis_spec_gap", gap_agent, context=[bench_task])
        merged = {
            **inputs,
            "benchmark_output": inputs.get("benchmark_output")
            or "(직전 Spec_Benchmarker 태스크 JSON 출력 전체를 Context에서 참조)",
        }
        result = self._run_sequential_crew(
            [bench_agent, gap_agent],
            [bench_task, gap_task],
            merged,
        )
        raws = self._crew_task_raws(result)
        benchmark = safe_parse_json(raws[0] if len(raws) > 0 else "{}")
        gap = safe_parse_json(raws[1] if len(raws) > 1 else "{}")
        return benchmark, gap

    def run_roadmap_and_dashboard(self, roadmap_inputs: dict, dashboard_inputs: dict) -> tuple[dict, dict]:
        """Crew B: Roadmap_Harness → Dashboard_Summarizer (순차 1회 kickoff)."""
        rm_agent = self.roadmap_harness()
        ds_agent = self.dashboard_summarizer()
        rm_task = self._make_task("synthesize_action_roadmap", rm_agent)
        dash_merged = {
            **dashboard_inputs,
            "phase1_actions": dashboard_inputs.get("phase1_actions")
            or "(직전 Roadmap_Harness 태스크 timeline 중 phase_num=1 actions — Context 참조)",
        }
        ds_task = self._make_task("summarize_dashboard", ds_agent, context=[rm_task])
        merged = {**roadmap_inputs, **dash_merged}
        result = self._run_sequential_crew(
            [rm_agent, ds_agent],
            [rm_task, ds_task],
            merged,
        )
        raws = self._crew_task_raws(result)
        roadmap = safe_parse_json(raws[0] if len(raws) > 0 else "{}")
        dashboard = safe_parse_json(raws[1] if len(raws) > 1 else "{}")
        return roadmap, dashboard

    def run_gap(self, inputs: dict) -> dict:
        """HITL 갭 재진단 전용 — 단독 Gap_Analyzer."""
        return safe_parse_json(self._run_single(self.gap_analyzer(), "diagnosis_spec_gap", inputs))

    def run_roadmap(self, inputs: dict) -> dict:
        return safe_parse_json(self._run_single(self.roadmap_harness(), "synthesize_action_roadmap", inputs))

    def run_dashboard(self, inputs: dict, benchmark_result: dict, gap_result: dict, roadmap_result: dict) -> dict:
        combined_inputs = {
            **inputs,
            "benchmark_context": benchmark_result,
            "gap_context": gap_result,
            "roadmap_context": roadmap_result,
        }
        return safe_parse_json(self._run_single(self.dashboard_summarizer(), "summarize_dashboard", combined_inputs))

    def run_jd_analysis(self, raw_text: str, target_url: str = "") -> dict:
        inputs = {"raw_text": raw_text, "target_url": target_url}
        return safe_parse_json(self._run_single(self.jd_structural_analyzer(), "structuralize_jd", inputs))

    def run_benchmark(self, inputs: dict) -> dict:
        return safe_parse_json(self._run_single(self.spec_benchmarker(), "benchmark_accepted_specs", inputs))


career_crew = LinkareerCareerCrew()
