"""KB Nederlandse Bibliografie Totaal metadata provider."""

from typing import Any

from bookflow.core.settings_registry import (
    ActionButton,
    CheckboxField,
    HeadingField,
    SettingsField,
    register_settings,
)
from bookflow.metadata_providers import register_provider
from bookflow.metadata_providers._kb_linked_data import (
    KbLinkedDataProvider,
    test_kb_connection,
)


@register_provider("kb_nbt")
class KbNbtProvider(KbLinkedDataProvider):
    """Search the public, CC0 Dutch National Bibliography graph."""

    name = "kb_nbt"
    display_name = "KB Nederlandse Bibliografie"
    requires_auth = False
    graph_uri = "http://data.bibliotheken.nl/nbt"
    author_graph_uri = "http://data.bibliotheken.nl/nta"
    resource_prefix = "http://data.bibliotheken.nl/id/nbt/"
    website_url = "https://data.bibliotheken.nl/KB/-/stories/Nederlandse-Bibliografie-Totaal-NBT"
    supports_isbn = True


def _test_kb_nbt_connection() -> dict[str, Any]:
    return test_kb_connection(KbNbtProvider())


@register_settings(
    "kb_nbt",
    "KB Nederlandse Bibliografie",
    icon="library",
    order=54,
    group="metadata_providers",
)
def kb_nbt_settings() -> list[SettingsField]:
    """KB NBT metadata provider settings."""
    return [
        HeadingField(
            key="kb_nbt_heading",
            title="KB Nederlandse Bibliografie Totaal",
            description=(
                "Public Dutch national bibliography for publications from, about, or in "
                "the Netherlands and Dutch language. Free, CC0, and no API key required."
            ),
            link_url=KbNbtProvider.website_url,
            link_text="data.bibliotheken.nl",
        ),
        CheckboxField(
            key="KB_NBT_ENABLED",
            label="Enable KB Nederlandse Bibliografie",
            description="Use the public KB bibliography for Dutch book searches and ISBN lookup.",
            default=False,
        ),
        ActionButton(
            key="test_connection",
            label="Test Connection",
            description="Verify the public KB Linked Data service is accessible",
            style="primary",
            callback=_test_kb_nbt_connection,
        ),
    ]
