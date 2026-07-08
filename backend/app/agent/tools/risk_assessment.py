"""多源灾害风险评估工具。"""
from __future__ import annotations

from typing import Any

from app.agent.tools.base_tool import EvidenceItem, BaseTool, ToolContext, ToolInput, ToolResult


class RiskAssessmentTool(BaseTool):
    name = "risk_assessment"
    description = "融合图谱、浏览器、文档、遥感等证据，生成风险评分、等级、原因和建议。"

    disaster_base_scores = {
        "暴雨洪涝": 0.52,
        "台风": 0.54,
        "地震": 0.58,
        "滑坡泥石流": 0.55,
        "火灾": 0.50,
        "干旱": 0.46,
    }
    current_time_keywords = ("今天", "当前", "现在", "近期", "未来24小时", "未来48小时", "未来72小时")
    high_warning_keywords = ("红色预警", "最高级别", "一级响应", "严重", "特大")
    warning_keywords = ("预警", "警报", "应急响应", "强降雨", "持续降雨")
    impact_keywords = ("淹没", "积水", "受灾", "塌方", "道路中断", "人员转移", "停电", "受损")

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        formal_memory = self._load_formal_memory(tool_input, context)
        if not self._is_confirmed_memory(formal_memory):
            return ToolResult(
                summary="尚未发现已确认的正式任务记忆，请先确认临时草稿后再进行风险评估。",
                need_user_confirm=True,
                confidence=0.35,
                data={"assessment_status": "missing_confirmed_memory"},
            )

        assessment = self._assess(formal_memory)
        confidence = self._estimate_confidence(assessment)
        if context:
            context.metadata["risk_assessment"] = assessment

        return ToolResult(
            summary=self._build_summary(assessment),
            evidence=[
                EvidenceItem(
                    source="risk_assessment",
                    type="fusion",
                    content=f"规则融合后得到{assessment['risk_level']}结论，评分为{assessment['risk_score']:.2f}",
                    confidence=confidence,
                    metadata={"risk_level": assessment["risk_level"]},
                )
            ],
            confidence=confidence,
            data={"assessment_status": "completed", "assessment": assessment},
        )

    def _load_formal_memory(
        self,
        tool_input: ToolInput,
        context: ToolContext | None,
    ) -> dict[str, Any]:
        params = tool_input.params or {}
        if params.get("formal_memory"):
            return params["formal_memory"]
        if context:
            return context.metadata.get("formal_memory", {})
        return {}

    def _is_confirmed_memory(self, formal_memory: dict[str, Any]) -> bool:
        return bool(formal_memory) and formal_memory.get("status") == "confirmed"

    def _assess(self, formal_memory: dict[str, Any]) -> dict[str, Any]:
        disaster_type = formal_memory.get("disaster_type", "未知")
        locations = formal_memory.get("locations") or []
        time_range = formal_memory.get("time_range", "未知")
        candidate_evidence = formal_memory.get("candidate_evidence") or []
        missing_info = list(formal_memory.get("missing_info") or [])

        risk_score = self.disaster_base_scores.get(disaster_type, 0.40)
        risk_factors = [f"任务灾害类型为{disaster_type}"] if disaster_type != "未知" else []
        basis = []

        if disaster_type != "未知":
            basis.append(f"已确认灾害类型：{disaster_type}")
        if locations:
            basis.append(f"已确认影响区域：{'、'.join(locations)}")
        if time_range != "未知":
            basis.append(f"已确认时间范围：{time_range}")

        if time_range in self.current_time_keywords:
            risk_score += 0.08
            risk_factors.append(f"时间范围为{time_range}，具有较强时效性")

        evidence_score, evidence_factors, evidence_basis = self._score_evidence(candidate_evidence)
        risk_score += evidence_score
        risk_factors.extend(evidence_factors)
        basis.extend(evidence_basis)

        for field in ("影响区域", "时间范围", "灾害类型"):
            if field in missing_info:
                risk_score -= 0.05

        risk_score = min(0.95, max(0.10, risk_score))
        risk_level = self._risk_level(risk_score)

        return {
            "risk_level": risk_level,
            "risk_score": round(risk_score, 2),
            "risk_factors": risk_factors,
            "affected_area": locations,
            "basis": basis,
            "suggestions": self._suggestions(disaster_type, risk_level),
            "missing_info": missing_info,
        }

    def _score_evidence(
        self,
        candidate_evidence: list[dict[str, Any]],
    ) -> tuple[float, list[str], list[str]]:
        score = 0.0
        risk_factors = []
        basis = []

        for item in candidate_evidence:
            content = str(item.get("content", ""))
            confidence = float(item.get("confidence") or 0.7)
            weighted_step = 0.08 if confidence >= 0.8 else 0.05

            if any(keyword in content for keyword in self.high_warning_keywords):
                score += weighted_step + 0.08
                risk_factors.append(f"证据显示高等级预警：{self._shorten(content)}")
            elif any(keyword in content for keyword in self.warning_keywords):
                score += weighted_step
                risk_factors.append(f"证据显示预警或响应信息：{self._shorten(content)}")

            if any(keyword in content for keyword in self.impact_keywords):
                score += weighted_step
                risk_factors.append(f"证据显示已出现影响：{self._shorten(content)}")

            if content:
                basis.append(f"{item.get('source', 'unknown')}：{self._shorten(content)}")

        return min(score, 0.35), risk_factors, basis

    def _risk_level(self, risk_score: float) -> str:
        if risk_score >= 0.85:
            return "极高风险"
        if risk_score >= 0.75:
            return "高风险"
        if risk_score >= 0.45:
            return "中风险"
        return "低风险"

    def _suggestions(self, disaster_type: str, risk_level: str) -> list[str]:
        suggestions = [
            "持续补充官方预警、现场反馈、遥感识别和文档证据。",
            "对低洼区、交通节点、医院学校等重点对象进行优先核查。",
        ]
        if disaster_type == "暴雨洪涝":
            suggestions.extend(
                [
                    "关注河道水位、城市积水点和排水设施运行情况。",
                    "必要时提前组织低洼区域人员转移和道路管制。",
                ]
            )
        elif disaster_type == "台风":
            suggestions.append("重点核查沿海风暴潮、临时构筑物和城市内涝风险。")
        elif disaster_type == "地震":
            suggestions.append("优先核查震中周边建筑受损、道路阻断和次生灾害风险。")

        if risk_level in {"高风险", "极高风险"}:
            suggestions.insert(0, "建议启动或升级应急响应，优先保障人员安全。")

        return suggestions

    def _estimate_confidence(self, assessment: dict[str, Any]) -> float:
        confidence = 0.82
        confidence -= len(assessment["missing_info"]) * 0.08
        if not assessment["basis"]:
            confidence -= 0.15
        return round(max(0.35, min(0.92, confidence)), 2)

    def _build_summary(self, assessment: dict[str, Any]) -> str:
        return (
            f"风险等级：{assessment['risk_level']}；"
            f"风险评分：{assessment['risk_score']:.2f}；"
            f"主要因素：{'、'.join(assessment['risk_factors']) or '证据不足'}。"
        )

    def _shorten(self, content: str, limit: int = 36) -> str:
        if len(content) <= limit:
            return content
        return content[:limit] + "..."
