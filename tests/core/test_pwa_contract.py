from pathlib import Path


def test_service_worker_keeps_push_clicks_inside_its_scope() -> None:
    worker = (
        Path(__file__).resolve().parents[2] / "src" / "frontend" / "public" / "service-worker.js"
    ).read_text(encoding="utf-8")

    assert "candidate.origin === scope.origin" in worker
    assert "candidate.href.startsWith(scope.href)" in worker
    assert "destination = scope.toString()" in worker


def test_service_worker_never_caches_private_routes() -> None:
    worker = (
        Path(__file__).resolve().parents[2] / "src" / "frontend" / "public" / "service-worker.js"
    ).read_text(encoding="utf-8")

    assert "request.url.includes('/api/')" in worker
    assert "request.url.includes('/socket.io/')" in worker
    assert "request.destination === 'image'" in worker
    assert "request.mode === 'navigate'" in worker
    assert "fetch(request)" in worker
