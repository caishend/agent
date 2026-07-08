import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import agent as agent_api
from app.db import Base
from app.models.task import Task


class AgentApiTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        db = self.SessionLocal()
        db.add(Task(task_id=1, user_id=1, task_name="成都暴雨测试任务"))
        db.commit()
        db.close()

        app = FastAPI()
        app.include_router(agent_api.router, prefix="/api/tasks")

        def override_db():
            session = self.SessionLocal()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[agent_api.get_db] = override_db
        app.dependency_overrides[agent_api.get_current_user_id] = lambda: 1
        self.client = TestClient(app)

    def test_agent_message_returns_events_and_task_draft(self):
        response = self.client.post(
            "/api/tasks/1/agent/message",
            json={"message": "请分析成都今天暴雨洪涝灾害风险"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["task_id"], 1)
        self.assertEqual(payload["events"][0]["type"], "thinking")
        self.assertTrue(any(event["type"] == "intent" for event in payload["events"]))
        draft_events = [
            event
            for event in payload["events"]
            if event.get("tool") == "task_draft" and event["type"] == "tool_result"
        ]
        self.assertEqual(draft_events[0]["data"]["draft"]["disaster_type"], "暴雨洪涝")
        self.assertTrue(draft_events[0]["need_user_confirm"])

    def test_confirm_draft_persists_formal_memory(self):
        draft = {
            "status": "pending_user_confirmation",
            "title": "成都今天暴雨洪涝分析任务草稿",
            "disaster_type": "暴雨洪涝",
            "locations": ["成都"],
            "time_range": "今天",
            "known_info": [{"field": "灾害类型", "value": "暴雨洪涝"}],
            "missing_info": [],
            "candidate_evidence": [],
            "source_message": "请分析成都今天暴雨洪涝灾害风险",
        }

        response = self.client.post(
            "/api/tasks/1/agent/confirm-draft",
            json={"draft": draft, "selected_fields": ["disaster_type", "locations"]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["data"]["memory_status"], "persisted")
        self.assertEqual(payload["data"]["formal_memory"]["disaster_type"], "暴雨洪涝")
        self.assertEqual(payload["data"]["formal_memory"]["locations"], ["成都"])

    def test_tool_endpoint_runs_graphrag_with_documents(self):
        response = self.client.post(
            "/api/tasks/1/tools/graphrag",
            json={
                "query": "为什么暴雨会导致内涝？",
                "params": {
                    "documents": [
                        {
                            "content": "暴雨会导致地表径流增加，排水不足时形成城市内涝。",
                            "metadata": {"source": "manual_doc"},
                        }
                    ]
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["data"]["retrieval_mode"], "provided_documents")
        self.assertEqual(payload["evidence"][0]["source"], "manual_doc")


if __name__ == "__main__":
    unittest.main()
