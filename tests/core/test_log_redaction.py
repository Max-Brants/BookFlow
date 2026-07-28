"""Security regression tests for application log redaction."""

import json
import logging

from bookflow.core.logger import JsonLogFormatter, SensitiveDataFilter, redact_log_text


def test_redacts_kobo_path_tokens_and_secret_query_values() -> None:
    raw = (
        "GET /api/kobo/super-secret-token/v1/library/sync"
        "?api_key=private&safe=value&access_token=also-private"
    )
    redacted = redact_log_text(raw)
    assert "super-secret-token" not in redacted
    assert "private" not in redacted
    assert "also-private" not in redacted
    assert "/api/kobo/<redacted>/" in redacted
    assert "safe=value" in redacted


def test_filter_redacts_formatted_arguments_before_handlers() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "request %s",
        ("/api/kobo/token-value/v1/library/sync",),
        None,
    )
    assert SensitiveDataFilter().filter(record)
    assert "token-value" not in record.getMessage()
    assert record.args == ()


def test_json_formatter_emits_machine_readable_fields() -> None:
    record = logging.LogRecord("bookflow", logging.INFO, __file__, 7, "ready", (), None)
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["logger"] == "bookflow"
    assert payload["level"] == "INFO"
    assert payload["message"] == "ready"
