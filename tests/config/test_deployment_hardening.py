"""Regression checks for deploy-time image and diagnostic safety."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("relative_path", "required_variable"),
    [
        ("compose/docker-compose.yml", "BOOKFLOW_IMAGE"),
        ("compose/docker-compose.tor.yml", "BOOKFLOW_IMAGE"),
        ("compose/docker-compose.wireguard.yml", "BOOKFLOW_IMAGE"),
        ("compose/docker-compose.lite.yml", "BOOKFLOW_LITE_IMAGE"),
    ],
)
def test_deployment_compose_requires_a_project_image_pin(
    relative_path: str, required_variable: str
) -> None:
    compose = (ROOT / relative_path).read_text(encoding="utf-8")

    assert f"image: ${{{required_variable}:?" in compose
    assert "ghcr.io/calibrain/bookflow" not in compose
    assert ":latest" not in compose


def test_debug_entrypoint_never_dumps_the_complete_environment() -> None:
    entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    assert "env | sort" not in entrypoint


def test_deployment_documentation_requires_an_immutable_project_digest() -> None:
    deployment = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")

    assert "BOOKFLOW_IMAGE=ghcr.io/timminater/bookflow@sha256:" in deployment
    assert "Never run an older image against a database" in deployment


def test_upstream_tracking_keeps_the_planned_baseline() -> None:
    upstream_tracking = (ROOT / "docs/upstream-tracking.md").read_text(encoding="utf-8")

    for sha in ("7bfa970", "00f3fa5", "28969ac", "81a057c", "8eb9bd5", "91b1064"):
        assert sha in upstream_tracking
