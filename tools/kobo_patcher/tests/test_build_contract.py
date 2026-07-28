# ruff: noqa: S101

from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = PROJECT.parents[1]


def test_onefile_build_emits_versioned_checksum_and_protocol_sbom() -> None:
    script = (PROJECT / "build.ps1").read_text(encoding="utf-8")
    for required in (
        "--onefile",
        "--windowed",
        "--noupx",
        "BookFlowKoboPatcher-$Version-win-x64.exe",
        ".sha256",
        ".spdx.json",
        "protocol_version = 1",
        "SPDXRef-Python",
        'pythonMajorMinor -ne "3.12"',
        'pythonBits -ne "64"',
        "Patcher icon is missing",
        "Patcher version metadata is missing",
    ):
        assert required in script


def test_workflow_tests_before_build_and_never_uses_secret_in_if() -> None:
    workflow = (REPOSITORY / ".github" / "workflows" / "kobo-patcher.yml").read_text(
        encoding="utf-8"
    )
    assert "python -m pytest tools/kobo_patcher/tests -q" in workflow
    assert "secrets.WINDOWS_SIGNING_CERT_BASE64 !=" not in workflow
    assert "No signing certificate configured" in workflow
    assert "Inspect self-contained EXE" in workflow
    assert "Get-AuthenticodeSignature" in workflow
