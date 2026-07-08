import unittest

from app.agent.tools.base_tool import ToolContext, ToolInput
from app.agent.tools.risk_assessment import RiskAssessmentTool


class RiskAssessmentToolTest(unittest.TestCase):
    def setUp(self):
        self.tool = RiskAssessmentTool()
        self.formal_memory = {
            "task_id": 5,
            "status": "confirmed",
            "title": "成都今天暴雨洪涝分析任务草稿",
            "disaster_type": "暴雨洪涝",
            "locations": ["成都"],
            "time_range": "今天",
            "missing_info": [],
            "candidate_evidence": [],
        }

    def test_requires_confirmed_formal_memory(self):
        result = self.tool.run(ToolInput(query="开始风险评估"), ToolContext(task_id=5))

        self.assertTrue(result.need_user_confirm)
        self.assertEqual(result.data["assessment_status"], "missing_confirmed_memory")

    def test_assesses_medium_risk_from_confirmed_flood_memory(self):
        context = ToolContext(task_id=5, metadata={"formal_memory": self.formal_memory})

        result = self.tool.run(ToolInput(query="开始风险评估"), context)
        assessment = result.data["assessment"]

        self.assertEqual(result.data["assessment_status"], "completed")
        self.assertEqual(assessment["risk_level"], "中风险")
        self.assertGreaterEqual(assessment["risk_score"], 0.5)
        self.assertIn("成都", assessment["affected_area"])
        self.assertIn("暴雨洪涝", assessment["basis"][0])
        self.assertGreater(len(assessment["suggestions"]), 0)

    def test_warning_and_inundation_evidence_raise_risk_level(self):
        memory = {
            **self.formal_memory,
            "candidate_evidence": [
                {
                    "source": "browser",
                    "type": "web",
                    "content": "成都市气象台发布暴雨红色预警",
                    "confidence": 0.92,
                },
                {
                    "source": "remote_sensing",
                    "type": "image_analysis",
                    "content": "遥感影像显示城区局部存在淹没区域",
                    "confidence": 0.88,
                },
            ],
        }
        context = ToolContext(task_id=5, metadata={"formal_memory": memory})

        result = self.tool.run(ToolInput(query="开始风险评估"), context)
        assessment = result.data["assessment"]

        self.assertEqual(assessment["risk_level"], "高风险")
        self.assertGreaterEqual(assessment["risk_score"], 0.75)
        self.assertTrue(any("红色预警" in factor for factor in assessment["risk_factors"]))
        self.assertTrue(any("淹没" in factor for factor in assessment["risk_factors"]))
        self.assertEqual(result.evidence[0].source, "risk_assessment")

    def test_missing_information_lowers_confidence(self):
        memory = {
            **self.formal_memory,
            "locations": [],
            "time_range": "未知",
            "missing_info": ["影响区域", "时间范围", "已有证据来源"],
        }
        context = ToolContext(task_id=5, metadata={"formal_memory": memory})

        result = self.tool.run(ToolInput(query="开始风险评估"), context)
        assessment = result.data["assessment"]

        self.assertLess(result.confidence, 0.7)
        self.assertIn("影响区域", assessment["missing_info"])
        self.assertIn("时间范围", assessment["missing_info"])


if __name__ == "__main__":
    unittest.main()
