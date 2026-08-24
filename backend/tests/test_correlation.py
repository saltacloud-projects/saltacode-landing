from fastapi.testclient import TestClient


def test_valid_correlation_id_is_preserved(client: TestClient) -> None:
    response = client.get(
        "/health/live",
        headers={"X-Correlation-ID": "valid-correlation-id"},
    )

    assert response.headers["x-correlation-id"] == "valid-correlation-id"


def test_unsafe_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get(
        "/health/live",
        headers={"X-Correlation-ID": "contains spaces and control\n"},
    )

    assert response.headers["x-correlation-id"] != "contains spaces and control"
    assert len(response.headers["x-correlation-id"]) == 36
