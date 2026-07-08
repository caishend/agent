"""遥感影像分析工具（占位实现）。"""
from app.agent.tools.base_tool import BaseTool


class RemoteSensingTool(BaseTool):
    name = "remote_sensing"
    description = "对卫星遥感影像进行语义分割，检测灾害区域并计算受影响面积。"

    def run(self, query: str) -> str:
        # TODO: 接入 SegFormer / U-Net 模型推理
        return (
            "【遥感分析结果（占位）】\n"
            "灾害类型：洪水\n"
            "受影响区域：东北部 A 区\n"
            "水体覆盖面积：3.2 km²\n"
            "置信度：0.91"
        )
