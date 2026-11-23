"""
[Chart Service] Plotly 기반 커리어 대시보드 시각화.

변수 유형에 맞는 차트만 노출합니다.
- 수치 단일값 → 게이지
- 명목×비중 → 도넛
- 명목(축)×수치 → 레이더
"""
from __future__ import annotations

from typing import Any

import plotly.graph_objects as go  # noqa: E402

# Linkareer 대시보드 팔레트 (파랑-흰색)
_PALETTE = {
    "primary": "#2563EB",
    "accent": "#3B82F6",
    "success": "#1E40AF",
    "warning": "#60A5FA",
    "danger": "#1D4ED8",
    "muted": "#94A3B8",
    "bg": "#F8FAFC",
    "prof": "#2563EB",
    "auth": "#60A5FA",
}
_SCORE_AXIS = dict(range=[0, 100], dtick=20, gridcolor="#E2E8F0", zeroline=True, zerolinecolor="#CBD5E1")

_CHART_GUIDE = [
    {"key": "readiness_gauge", "vars": "수치형(연속)", "chart": "게이지", "reason": "단일 준비도(0~100%) 현재 수준"},
    {"key": "category_donut", "vars": "명목(유형)×비중", "chart": "도넛", "reason": "전체 Gap 중 유형별 상대 비율"},
    {"key": "benchmark_radar", "vars": "명목(축)×수치(점수)", "chart": "레이더", "reason": "다축 역량 균형·프로필 비교"},
]


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, float(v or 0)))


def _gap_report(gap: dict | None) -> list[dict]:
    if not gap:
        return []
    return list(gap.get("gap_analysis_report") or gap.get("gaps") or [])


class ChartService:
    """커리어 하네스 대시보드 차트 생성기."""

    def build_dashboard_charts(
        self,
        *,
        gap_output: dict | None = None,
        benchmark_output: dict | None = None,
        dashboard_summary: dict | None = None,
        roadmap_result: dict | None = None,
        target_field: str = "",
        target_job: str = "",
        target_company: str = "",
    ) -> dict[str, Any]:
        gap = gap_output or {}
        bench = benchmark_output or {}
        report = _gap_report(gap)

        plotly: dict[str, Any] = {}
        plotly["readiness_gauge"] = self._readiness_gauge(gap)
        plotly["category_donut"] = self._category_donut(report)
        if bench:
            plotly["benchmark_radar"] = self._benchmark_radar(bench, gap)

        meta = {
            "target": f"{target_field} · {target_job} · {target_company}".strip(" ·"),
            "gap_count": len(report),
            "total_gap": gap.get("total_gap_percentage"),
            "engines": ["plotly"],
            "chart_guide": _CHART_GUIDE,
        }
        if dashboard_summary:
            meta["executive_preview"] = (dashboard_summary.get("total_summary")
                                         or dashboard_summary.get("executive_summary") or "")[:120]

        return {
            "plotly": {k: v for k, v in plotly.items() if v},
            "static": {},
            "meta": meta,
        }

    def _readiness_gauge(self, gap: dict) -> dict | None:
        total = gap.get("total_gap_percentage")
        if total is None:
            return None
        readiness = _clamp(100 - float(total))
        if readiness >= 60:
            color = "#16A34A"
        elif readiness >= 40:
            color = "#EAB308"
        else:
            color = "#DC2626"
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=readiness,
            number={"suffix": "%", "font": {"size": 42, "color": color, "family": "Pretendard, sans-serif"}},
            title={"text": "취업 준비도", "font": {"size": 16, "color": "#475569"}},
            delta={"reference": 70, "increasing": {"color": _PALETTE["success"]}, "decreasing": {"color": _PALETTE["danger"]}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#CBD5E1"},
                "bar": {"color": color, "thickness": 0.28},
                "bgcolor": "#F1F5F9",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 40], "color": "rgba(37,99,235,0.12)"},
                    {"range": [40, 70], "color": "rgba(59,130,246,0.12)"},
                    {"range": [70, 100], "color": "rgba(30,64,175,0.12)"},
                ],
            },
        ))
        fig.update_layout(
            height=280, margin=dict(l=24, r=24, t=48, b=12),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font={"family": "Pretendard, Malgun Gothic, sans-serif"},
        )
        return fig.to_plotly_json()

    def _category_donut(self, report: list[dict]) -> dict | None:
        if not report:
            return None
        prof, auth = 0, 0
        for r in report:
            cat = str(r.get("category") or "")
            sev = float(r.get("severity_score") or 0)
            if "진정성" in cat:
                auth += sev
            else:
                prof += sev
        if prof + auth <= 0:
            return None
        fig = go.Figure(go.Pie(
            labels=["전문성 Gap", "진정성 Gap"],
            values=[prof, auth],
            hole=0.55,
            marker=dict(colors=[_PALETTE["prof"], _PALETTE["auth"]], line=dict(color="#fff", width=2)),
            textinfo="percent",
            textposition="inside",
            textfont=dict(size=11),
            hovertemplate="%{label}<br>가중 시급성: %{value:.0f}<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text="Gap 유형 분포", font=dict(size=15, color="#334155"), x=0.5, xanchor="center"),
            height=320, margin=dict(l=16, r=16, t=48, b=72),
            paper_bgcolor="rgba(0,0,0,0)",
            showlegend=True,
            legend=dict(orientation="h", yanchor="top", y=-0.28, x=0.5, xanchor="center"),
        )
        return fig.to_plotly_json()

    def _benchmark_radar(self, bench: dict, gap: dict) -> dict | None:
        auth = _clamp(gap.get("authenticity_score") or 50)
        prof = _clamp(gap.get("professionalism_score") or 50)
        readiness = _clamp(100 - float(gap.get("total_gap_percentage") or 50))
        gpa = _clamp((float(bench.get("average_gpa") or 3.2) / 4.5) * 100)
        cert_n = min(100, len(bench.get("common_certificates") or []) * 25)
        lang_n = min(100, len(bench.get("average_language_scores") or []) * 30)

        categories = ["진정성", "전문성", "준비도", "학점", "자격증", "어학"]
        values = [auth, prof, readiness, gpa, cert_n, lang_n]
        values_closed = values + [values[0]]
        cats_closed = categories + [categories[0]]

        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(
            r=values_closed, theta=cats_closed,
            fill="toself", fillcolor="rgba(37,99,235,0.15)",
            line=dict(color=_PALETTE["primary"], width=2.5),
            name="현재 스펙",
        ))
        fig.add_trace(go.Scatterpolar(
            r=[85] * len(cats_closed), theta=cats_closed,
            fill="toself", fillcolor="rgba(96,165,250,0.1)",
            line=dict(color=_PALETTE["success"], width=1, dash="dot"),
            name="합격자 기준(참고)",
        ))
        fig.update_layout(
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 100], gridcolor="#E2E8F0", tickfont=dict(size=9)),
                bgcolor="rgba(0,0,0,0)",
            ),
            title=dict(text="스펙 vs 합격자 프로필", font=dict(size=15, color="#334155"), x=0),
            height=340, margin=dict(l=48, r=48, t=56, b=24),
            paper_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=-0.12, x=0.5, xanchor="center"),
        )
        return fig.to_plotly_json()


chart_service = ChartService()
