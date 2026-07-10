import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.agent.tools.base_tool import ToolContext, ToolInput
from app.agent.tools.disaster_detector import DisasterObjectDetector
from app.agent.tools.remote_sensing import RemoteSensingTool


class DisasterObjectDetectorTest(unittest.TestCase):
    def test_detects_synthetic_disaster_regions(self):
        image = Image.new("RGB", (120, 80), (35, 120, 35))
        for x in range(10, 55):
            for y in range(15, 60):
                image.putpixel((x, y), (30, 90, 170))
        for x in range(75, 105):
            for y in range(10, 32):
                image.putpixel((x, y), (230, 80, 20))

        detections = DisasterObjectDetector(min_area_ratio=0.002).detect(image, mode="flood")
        labels = {item["label"] for item in detections}

        self.assertIn("flood_water", labels)
        self.assertIn("active_fire", labels)
        self.assertTrue(all(len(item["bbox"]) == 4 for item in detections))
        self.assertTrue(all(0 < item["confidence"] <= 1 for item in detections))

    def test_remote_sensing_tool_returns_detection_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "flood.png"
            image = Image.new("RGB", (80, 60), (50, 130, 55))
            for x in range(12, 68):
                for y in range(18, 50):
                    image.putpixel((x, y), (25, 95, 180))
            image.save(image_path)

            result = RemoteSensingTool().run(
                ToolInput(
                    query="detect flood disaster objects",
                    params={"image_path": str(image_path), "use_disaster_pipeline": False},
                ),
                ToolContext(task_id=999, user_id=1),
            )

        self.assertEqual(result.data["remote_sensing_status"], "analyzed")
        self.assertGreater(result.data["aggregate"]["detection_count"], 0)
        self.assertTrue(any(item.type == "object_detection" for item in result.artifacts))
        self.assertTrue(result.data["images"][0]["detections"])

    def test_remote_sensing_falls_back_when_pipeline_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "fallback.png"
            image = Image.new("RGB", (80, 60), (50, 130, 55))
            for x in range(12, 68):
                for y in range(18, 50):
                    image.putpixel((x, y), (25, 95, 180))
            image.save(image_path)

            result = RemoteSensingTool().run(
                ToolInput(
                    query="detect flood disaster objects",
                    params={
                        "image_path": str(image_path),
                        "use_disaster_pipeline": True,
                        "disaster_model_dir": "missing-disaster-model-dir",
                    },
                ),
                ToolContext(task_id=999, user_id=1),
            )

        image_result = result.data["images"][0]
        self.assertEqual(result.data["remote_sensing_status"], "analyzed")
        self.assertEqual(image_result["model_status"], "fallback")
        self.assertTrue(image_result["model_error"])
        self.assertGreater(result.data["aggregate"]["detection_count"], 0)

    def test_remote_sensing_accepts_multiple_uploaded_images_with_attachment_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_paths = []
            for name in ("first.jpg", "second.jpg"):
                image_path = Path(tmp) / name
                image = Image.new("RGB", (40, 30), (25, 95, 180))
                image.save(image_path)
                image_paths.append(image_path)

            result = RemoteSensingTool().run(
                ToolInput(
                    query="识别图片灾害\n\n已随本轮发送附件：first.jpg、second.jpg",
                    files=[
                        {
                            "path": str(image_paths[0]),
                            "name": "first.jpg",
                            "type": "IMAGE",
                            "mime_type": "image/jpeg",
                        },
                        {
                            "path": str(image_paths[1]),
                            "name": "second.jpg",
                            "type": "IMAGE",
                            "mime_type": "image/jpeg",
                        },
                    ],
                    params={"use_disaster_pipeline": False},
                ),
                ToolContext(task_id=999, user_id=1),
            )

        self.assertEqual(result.data["remote_sensing_status"], "analyzed")
        self.assertEqual(len(result.data["images"]), 2)


if __name__ == "__main__":
    unittest.main()
