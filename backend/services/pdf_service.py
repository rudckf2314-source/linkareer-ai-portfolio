"""[Business Service Layer] ReportLab 기반 스펙 진단 PDF 스트림 빌더."""
import io
import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

from core.models import RoadmapPdfRequest, UserSpecSchema


class PDFService:
    """
    유저 스펙 → 스타일링된 진단서 PDF(bytes) 빌더.
    라우터는 폰트/패딩 등 가공 상세를 알 필요 없이 build(spec)만 호출한다.
    """

    PRIMARY = colors.HexColor("#0071e3")

    def __init__(self) -> None:
        self._font = "Helvetica"
        self._font_bold = "Helvetica-Bold"
        self._register_korean_font()

    def _register_korean_font(self) -> None:
        import os
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        windir = os.environ.get("WINDIR", "C:\\Windows")
        candidates = [
            # Windows: Malgun Gothic (Regular / Bold)
            (os.path.join(windir, "Fonts", "malgun.ttf"), os.path.join(windir, "Fonts", "malgunbd.ttf"), "MalgunGothic"),
            # macOS: AppleGothic
            ("/System/Library/Fonts/Supplemental/AppleGothic.ttf", "/System/Library/Fonts/Supplemental/AppleGothic.ttf", "AppleGothic"),
            ("/Library/Fonts/AppleGothic.ttf", "/Library/Fonts/AppleGothic.ttf", "AppleGothic"),
            # macOS fallback: AppleMyungjo
            ("/System/Library/Fonts/Supplemental/AppleMyungjo.ttf", "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf", "AppleMyungjo"),
            # Linux: Nanum Gothic
            ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "NanumGothic"),
            ("/usr/share/fonts/nanum/NanumGothic.ttf", "/usr/share/fonts/nanum/NanumGothicBold.ttf", "NanumGothic"),
        ]

        registered = False
        for reg_path, bold_path, font_name in candidates:
            if os.path.exists(reg_path):
                try:
                    pdfmetrics.registerFont(TTFont(font_name, reg_path))
                    self._font = font_name
                    
                    bold_name = f"{font_name}-Bold"
                    if os.path.exists(bold_path) and bold_path != reg_path:
                        try:
                            pdfmetrics.registerFont(TTFont(bold_name, bold_path))
                            self._font_bold = bold_name
                        except Exception:
                            self._font_bold = font_name
                    else:
                        self._font_bold = font_name
                    
                    registered = True
                    break
                except Exception:
                    continue

        if not registered:
            self._font = "Helvetica"
            self._font_bold = "Helvetica-Bold"

    def _style(self, name, size, bold=False, color=colors.HexColor("#1d1d1f"), space_after=6, align=TA_LEFT):
        return ParagraphStyle(
            name, fontName=self._font_bold if bold else self._font, fontSize=size,
            leading=size + 5, textColor=color, spaceAfter=space_after, alignment=align,
            wordWrap='CJK'
        )

    @staticmethod
    def _esc(text) -> str:
        s = str(text) if text is not None else ""
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def build(self, spec: UserSpecSchema) -> bytes:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=18 * mm, bottomMargin=18 * mm, title="스펙 진단서",
        )
        el = []
        b, mp = spec.basic_info, spec.matching_preference

        el.append(Paragraph(self._esc(f"{b.name} 스펙 진단서"), self._style("t", 22, True, self.PRIMARY, 2)))
        el.append(Paragraph(self._esc(f"생성일 {datetime.now():%Y-%m-%d %H:%M} · Linkareer AI Career Hub"),
                            self._style("sub", 9, False, colors.HexColor("#86868b"), 4)))
        el.append(HRFlowable(width="100%", thickness=1.2, color=self.PRIMARY, spaceAfter=12))

        def section(title: str):
            el.append(Spacer(1, 6))
            el.append(Paragraph(self._esc(title), self._style("h", 14, True, self.PRIMARY, 6)))

        def kv_table(rows):
            t = Table(
                [[Paragraph(self._esc(k), self._style("k", 10, True)), Paragraph(self._esc(v), self._style("v", 10))]
                 for k, v in rows],
                colWidths=[40 * mm, 130 * mm],
            )
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e5ea")),
            ]))
            el.append(t)

        section("기본 정보")
        kv_table([
            ["최종학력", f"{b.final_education} ({b.graduation_status})"],
            ["학교 / 전공", f"{b.school_name} / {b.major}"],
            ["학점", f"{b.gpa.score} / {b.gpa.max_score}"],
        ])

        section("희망 조건")
        kv_table([
            ["희망 직무", mp.desired_job],
            ["희망 기업형태", mp.desired_company_type],
            ["희망 산업군", mp.desired_industry],
        ])

        if spec.languages:
            section("어학")
            kv_table([[l.language_type, f"{l.score} ({l.acquisition_date})"] for l in spec.languages])
        if spec.certificates:
            section("자격증")
            kv_table([[c.name, f"{c.issuer} ({c.acquisition_date})"] for c in spec.certificates])
        if spec.careers:
            section("경력 사항")
            for c in spec.careers:
                el.append(Paragraph(self._esc(f"{c.company_name} · {c.employment_type} ({c.start_date} ~ {c.end_date or '재직 중'})"),
                                   self._style("ci", 11, True, space_after=2)))
                el.append(Paragraph(self._esc(c.role_summary), self._style("cs", 10, False, colors.HexColor("#3a3a3c"), 8)))
        if spec.activities:
            section("대외 활동")
            for a in spec.activities:
                award = f" · 수상: {a.award}" if a.award else ""
                el.append(Paragraph(self._esc(f"{a.organization_or_name} ({a.activity_type}, {a.start_date} ~ {a.end_date}){award}"),
                                   self._style("ai", 11, True, space_after=2)))
                el.append(Paragraph(self._esc(a.summary), self._style("as", 10, False, colors.HexColor("#3a3a3c"), 8)))

        el.append(Spacer(1, 16))
        el.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#d1d1d6"), spaceAfter=6))
        el.append(Paragraph(self._esc("본 문서는 Linkareer AI Career Hub에서 자동 생성된 스펙 진단서입니다."),
                           self._style("foot", 8, False, colors.HexColor("#86868b"), 0)))

        doc.build(el)
        buf.seek(0)
        return buf.read()

    def _para(self, text: str, style_name: str = "b", size: int = 10, bold: bool = False,
              color=colors.HexColor("#1d1d1f"), space_after: int = 4):
        return Paragraph(self._esc(text), self._style(style_name, size, bold, color, space_after))

    def _section_title(self, el: list, title: str) -> None:
        el.append(Spacer(1, 8))
        el.append(self._para(title, "h", 13, True, self.PRIMARY, 6))

    def _bullet_list(self, el: list, items: list[str], indent: str = "• ") -> None:
        for item in items:
            if item and str(item).strip():
                el.append(self._para(f"{indent}{item}", "bl", 9, False, colors.HexColor("#3a3a3c"), 3))

    def build_roadmap_dashboard(self, payload: RoadmapPdfRequest) -> bytes:
        """정밀 로드맵 HITL 대시보드 → PDF 리포트."""
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
            topMargin=16 * mm, bottomMargin=16 * mm, title="커리어 마스터 로드맵",
        )
        el: list = []
        rm = payload.roadmap_result or {}
        name = (payload.user_name or "지원자").strip()

        el.append(self._para("커리어 마스터 로드맵 리포트", "t", 20, True, self.PRIMARY, 2))
        el.append(self._para(
            f"{name} · 생성일 {datetime.now():%Y-%m-%d %H:%M} · Linkareer AI Career Hub",
            "sub", 9, False, colors.HexColor("#86868b"), 4,
        ))
        el.append(HRFlowable(width="100%", thickness=1.2, color=self.PRIMARY, spaceAfter=10))

        self._section_title(el, "목표 직무")
        target_rows = [
            ["분야", payload.target_field],
            ["기업", payload.target_company],
            ["직무", payload.target_job],
        ]
        t = Table(
            [[Paragraph(self._esc(k), self._style("k", 9, True)),
              Paragraph(self._esc(v), self._style("v", 9))] for k, v in target_rows],
            colWidths=[28 * mm, 142 * mm],
        )
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e5ea")),
        ]))
        el.append(t)

        crit = payload.benchmark_output or {}
        if crit:
            self._section_title(el, "① 합격자 스펙 벤치마킹")
            if crit.get("summary"):
                el.append(self._para(crit["summary"], "cs", 9, False, colors.HexColor("#3a3a3c"), 6))
            for label, key in (("전문성", "professionalism_criteria"), ("진정성", "authenticity_criteria")):
                items = crit.get(key) or crit.get(key.replace("_criteria", "")) or []
                if items:
                    el.append(self._para(label, "cl", 10, True, space_after=3))
                    for it in items[:6]:
                        if not isinstance(it, dict):
                            continue
                        title = it.get("criteria") or it.get("item") or ""
                        narr = it.get("narrative") or it.get("reason") or ""
                        line = title
                        if narr:
                            line += f" — {narr}"
                        el.append(self._para(line, "ci", 9, False, colors.HexColor("#3a3a3c"), 4))

        gap = payload.gap_output or {}
        gap_report = rm.get("gap_analysis_report") or []
        if gap or gap_report:
            self._section_title(el, "② 진정성·전문성 갭 진단")
            total = gap.get("total_gap_percentage")
            if total is None:
                total = rm.get("total_gap_percentage")
            if total is not None:
                el.append(self._para(f"종합 부족도: {round(float(total))}%", "gt", 10, True, space_after=4))
            if gap.get("feedback"):
                el.append(self._para(gap["feedback"], "gf", 9, False, colors.HexColor("#3a3a3c"), 6))
            for g in gap_report[:8]:
                if not isinstance(g, dict):
                    continue
                req = g.get("required_criteria", "")
                desc = g.get("gap_description", "")
                sev = g.get("severity_score", "")
                cat = g.get("category", "")
                el.append(self._para(f"[{cat}] {req} (부족 {sev}%)", "gi", 9, True, space_after=2))
                if desc:
                    el.append(self._para(desc, "gd", 8, False, colors.HexColor("#6e6e73"), 4))

        bridge = rm.get("narrative_bridge_report") or {}
        if bridge:
            self._section_title(el, "③ 서사 연결 브릿지")
            if bridge.get("summary"):
                el.append(self._para(bridge["summary"], "bs", 9, False, colors.HexColor("#3a3a3c"), 4))
            if bridge.get("storyline"):
                el.append(self._para(f"서사 줄기: {bridge['storyline']}", "bln", 9, True, space_after=6))
            for b in (bridge.get("experience_bridges") or [])[:5]:
                if not isinstance(b, dict):
                    continue
                line = f"{b.get('from_experience', '')} → {b.get('to_experience', '')}"
                if b.get("causal_link"):
                    line += f" ({b['causal_link']})"
                el.append(self._para(line, "bb", 8, False, colors.HexColor("#5856d6"), 3))

        certs = rm.get("required_certifications") or []
        needed = [c for c in certs if isinstance(c, dict) and c.get("status") != "보유"]
        if needed:
            self._section_title(el, "취득 필요 자격증")
            for c in needed[:10]:
                name_c = c.get("name", "")
                pri = c.get("priority", "권장")
                reason = c.get("reason", "")
                phase = c.get("target_phase", 3)
                el.append(self._para(f"{name_c} [{pri}] · Phase {phase}", "cn", 9, True, space_after=2))
                if reason:
                    el.append(self._para(reason, "cr", 8, False, colors.HexColor("#6e6e73"), 4))

        timeline = rm.get("timeline") or []
        if timeline:
            self._section_title(el, "④ 4-Phase 커리어 마스터 타임라인")
            for m in timeline:
                if not isinstance(m, dict):
                    continue
                pnum = m.get("phase_num", "")
                title = m.get("phase_title", "")
                period = m.get("period", "")
                el.append(self._para(f"Phase {pnum}: {title} ({period})", "ph", 11, True, self.PRIMARY, 3))
                directive = m.get("narrative_bridge_directive", "")
                if directive:
                    el.append(self._para(directive, "pd", 8, False, colors.HexColor("#5856d6"), 4))
                actions = m.get("actions") or []
                self._bullet_list(el, actions[:6])
                phase_certs = m.get("required_certifications") or []
                if phase_certs:
                    labels = [str(x).strip() for x in phase_certs if str(x).strip()]
                    if labels:
                        el.append(self._para(f"자격증: {', '.join(labels)}", "pc", 8, False, colors.HexColor("#c93400"), 3))
                sources = m.get("sources") or []
                for s in sources[:5]:
                    if not isinstance(s, dict):
                        continue
                    st = s.get("title", "")
                    sp = s.get("source_platform", "")
                    if st:
                        el.append(self._para(f"· [{sp}] {st}", "src", 8, False, colors.HexColor("#6e6e73"), 2))
                outcome = m.get("expected_outcome", "")
                if outcome:
                    el.append(self._para(f"기대 성과: {outcome}", "po", 8, True, colors.HexColor("#248a3d"), 6))
                el.append(Spacer(1, 4))

        el.append(Spacer(1, 12))
        el.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#d1d1d6"), spaceAfter=6))
        el.append(self._para(
            "본 문서는 Linkareer AI Career Hub 정밀 로드맵 대시보드에서 자동 생성된 리포트입니다.",
            "foot", 8, False, colors.HexColor("#86868b"), 0,
        ))

        doc.build(el)
        buf.seek(0)
        return buf.read()


# 싱글톤 인스턴스
pdf_service = PDFService()
