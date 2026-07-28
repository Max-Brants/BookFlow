from __future__ import annotations

from bookflow.core.release_candidates import (
    ReleaseCandidate,
    ReleaseProfile,
    candidate_fingerprint,
    evaluate_candidate,
    rank_candidates,
)


def test_fingerprint_precedence_and_url_secret_is_not_exposed():
    candidate = ReleaseCandidate(
        source="Prowlarr",
        title="Book",
        indexer="Indexer",
        guid="guid-1",
        info_hash="ignored",
        download_url="https://user:secret@example.com/download?token=secret",
    )

    fingerprint = candidate_fingerprint(candidate)

    assert fingerprint == "prowlarr:indexer-guid:indexer:guid-1"
    assert "secret" not in fingerprint


def test_hard_filters_reject_executables_and_wrong_language():
    profile = ReleaseProfile(
        title="Dune",
        language="en",
        allowed_formats=("epub",),
        allowed_protocols=("torrent",),
    )
    candidate = ReleaseCandidate(
        source="test",
        title="Dune",
        language="nl",
        format="epub",
        protocol="torrent",
        files=("Dune.epub", "setup.exe"),
    )

    result = evaluate_candidate(candidate, profile)

    assert result.accepted is False
    assert result.reject_reasons == ("language_mismatch", "suspicious_executable")


def test_ranking_is_deterministic_and_explainable():
    profile = ReleaseProfile(
        title="Dune",
        authors=("Frank Herbert",),
        language="en",
        publish_year=1965,
        allowed_formats=("kepub", "epub"),
        allowed_protocols=("torrent",),
        positive_terms=("retail",),
        indexer_priorities={"preferred": 7},
    )
    candidates = [
        ReleaseCandidate(
            source="other",
            title="Dune retail",
            author="Frank Herbert",
            language="en",
            format="epub",
            protocol="torrent",
            seeders=10,
            publish_year=1965,
        ),
        ReleaseCandidate(
            source="preferred",
            indexer="preferred",
            title="Dune retail",
            author="Frank Herbert",
            language="en",
            format="kepub",
            protocol="torrent",
            seeders=10,
            publish_year=1965,
        ),
    ]

    ranked = rank_candidates(candidates, profile)

    assert ranked[0][0].format == "kepub"
    assert ranked[0][1].components["source_priority"] == 7
    assert ranked == rank_candidates(list(reversed(candidates)), profile)


def test_profile_fingerprint_is_order_stable():
    first = ReleaseProfile(title="Dune", allowed_formats=("epub", "kepub"))
    second = ReleaseProfile(title="Dune", allowed_formats=("kepub", "epub"))

    assert first.fingerprint() == second.fingerprint()
