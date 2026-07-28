from bookflow.config.settings import _on_save_bestseller, bestseller_settings


def test_bestseller_settings_expose_enabled_and_bounded_interval() -> None:
    fields = {field.key: field for field in bestseller_settings()}

    assert fields["BESTSELLER_ENABLED"].default is True
    interval = fields["BESTSELLER_CHECK_INTERVAL_HOURS"]
    assert interval.default == 24
    assert interval.min_value == 1
    assert interval.max_value == 168


def test_bestseller_interval_save_validation_normalizes_integer_values() -> None:
    assert _on_save_bestseller({"BESTSELLER_CHECK_INTERVAL_HOURS": "12"}) == {
        "error": False,
        "values": {"BESTSELLER_CHECK_INTERVAL_HOURS": 12},
    }
    assert _on_save_bestseller({"BESTSELLER_CHECK_INTERVAL_HOURS": 0})["error"] is True
    assert _on_save_bestseller({"BESTSELLER_CHECK_INTERVAL_HOURS": True})["error"] is True
