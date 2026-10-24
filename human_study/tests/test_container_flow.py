"""Opt-in external container test; never deploys or provisions cloud resources."""
import os

import httpx
import pytest


@pytest.mark.skipif(not os.environ.get("DTAG_TEST_CONTAINER_URL"), reason="set DTAG_TEST_CONTAINER_URL to a running local test container")
def test_container_health_assets_port_and_full_fixture_flow():
    url = os.environ["DTAG_TEST_CONTAINER_URL"].rstrip("/")
    with httpx.Client(base_url=url, headers={"Origin": url}, timeout=30) as client:
        assert client.get("/api/human/health").json() == {"status": "ok"}
        assert client.get("/api/human/readiness").json() == {"status": "ready"}
        page = client.get("/study")
        assert page.status_code == 200 and '<div id="root">' in page.text
        for path in ("/docs", "/api/profiles", "/api/sessions"):
            assert client.get(path).status_code == 404
        view = client.post("/api/human/start", json={}).json()
        view = client.post("/api/human/consent", json={"accepted": True,
                            "expected_session_version": view["session_version"]}).json()
        for _ in range(37):
            question = view["question"]
            response = client.post("/api/human/answer", json={"question_id": question["question_id"],
                "answer_value": question["choices"][0]["value"], "idempotency_key": question["question_id"],
                "expected_session_version": view["session_version"]})
            assert response.status_code == 200, response.text
            view = response.json()["current"]
        assert view["phase"] == "ready_to_complete"
        view = client.post("/api/human/complete", json={}).json()
        assert view["phase"] == "complete" and view["receipt"]
        assert client.get("/api/human/receipt").json()["receipt"] == view["receipt"]
