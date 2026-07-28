from bookflow.metadata_providers.hardcover import HardcoverProvider, _compute_search_title


class TestHardcoverComputeSearchTitle:
    def test_prefers_subtitle_when_title_contains_subtitle(self):
        assert (
            _compute_search_title("Mistborn: The Final Empire", "The Final Empire")
            == "The Final Empire"
        )

    def test_prefers_main_title_when_subtitle_is_descriptive(self):
        assert (
            _compute_search_title(
                "The Cuckoo's Egg: Tracking a Spy Through the Maze of Computer Espionage",
                "Tracking a Spy Through the Maze of Computer Espionage",
            )
            == "The Cuckoo's Egg"
        )

    def test_does_not_use_subtitle_when_it_looks_like_series_position(self):
        assert _compute_search_title("The Stormlight Archive: Book 1", "Book 1") is None
        assert _compute_search_title("Some Series: Volume II", "Volume II") is None

    def test_strips_series_prefix_when_series_name_available(self):
        assert (
            _compute_search_title("Mistborn: The Final Empire", None, series_name="Mistborn")
            == "The Final Empire"
        )

    def test_strips_parenthetical_suffix(self):
        assert _compute_search_title("The Martian (Unabridged)", None) == "The Martian"
        assert _compute_search_title("The Martian", None) is None

    def test_returns_none_when_no_useful_simplification(self):
        assert _compute_search_title("Dune", None) is None


def test_batch_isbn_lookup_uses_one_graphql_query(monkeypatch):
    provider = HardcoverProvider(api_key="test-token")
    calls = []

    def execute(query, variables, *, raise_on_error=False):
        calls.append((query, variables, raise_on_error))
        return {
            "editions": [
                {
                    "isbn_10": None,
                    "isbn_13": "9780000000019",
                    "book": {"id": 1, "title": "Eerste boek", "contributions": []},
                },
                {
                    "isbn_10": None,
                    "isbn_13": "9780000000026",
                    "book": {"id": 2, "title": "Tweede boek", "contributions": []},
                },
            ]
        }

    monkeypatch.setattr(provider, "_execute_query", execute)

    matches = provider.search_by_isbns_for_enrichment(["9780000000019", "9780000000026"])

    assert set(matches) == {"9780000000019", "9780000000026"}
    assert len(calls) == 1
    assert calls[0][1] == {"isbns": ["9780000000019", "9780000000026"]}
    assert calls[0][2] is True
