from bookflow.core.metrics import RequestMetrics


def test_request_metrics_render_bounded_prometheus_output() -> None:
    metrics = RequestMetrics()
    metrics.observe(method="get", status=200, duration_seconds=0.25)
    metrics.observe(method="GET", status=200, duration_seconds=0.5)
    metrics.observe(method="POST", status=409, duration_seconds=-1)

    rendered = metrics.render()
    assert 'bookflow_http_requests_total{method="GET",status="200"} 2' in rendered
    assert 'bookflow_http_requests_total{method="POST",status="409"} 1' in rendered
    assert "bookflow_http_request_duration_seconds_total 0.750000" in rendered
    assert "bookflow_http_requests_observed 3" in rendered
