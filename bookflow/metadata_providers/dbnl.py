"""Digitale Bibliotheek voor de Nederlandse Letteren metadata provider."""

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


@register_provider("dbnl")
class DbnlProvider(KbLinkedDataProvider):
    """Search public DBNL title and author linked data."""

    name = "dbnl"
    display_name = "DBNL"
    requires_auth = False
    graph_uri = "http://data.bibliotheken.nl/dbnlt"
    author_graph_uri = "http://data.bibliotheken.nl/dbnla"
    resource_prefix = "http://data.bibliotheken.nl/id/dbnlt/"
    website_url = "https://data.bibliotheken.nl/KB/-/stories/Titels-DBNL"
    default_language = "nl"

    def _build_record_query(self, resource_uri: str) -> str:
        return self._dbnl_details_query([resource_uri])

    def _build_details_for_resources(self, resource_uris: list[str]) -> str:
        safe_resources = [
            resource_uri
            for resource_uri in resource_uris
            if resource_uri.startswith(self.resource_prefix)
            and self._normalize_provider_id(resource_uri)
        ]
        return self._dbnl_details_query(safe_resources)

    def _dbnl_details_query(self, resource_uris: list[str]) -> str:
        """Fetch DBNL details with its title graph as the default graph."""
        values = " ".join(f"<{resource_uri}>" for resource_uri in resource_uris)
        query = f"""
PREFIX schema: <http://schema.org/>
PREFIX dcterms: <http://purl.org/dc/terms#>
SELECT ?book ?title ?author ?authorName ?description ?date ?url
FROM <{self.graph_uri}>
FROM NAMED <{self.author_graph_uri}>
WHERE {{
  VALUES ?book {{ {values} }}
  ?book schema:name ?title .
  OPTIONAL {{ ?book schema:author ?author . }}
  OPTIONAL {{ ?book schema:description ?description . }}
  OPTIONAL {{ ?book dcterms:issued ?date . }}
  OPTIONAL {{ ?book schema:datePublished ?date . }}
  OPTIONAL {{ ?book schema:dateCreated ?date . }}
  OPTIONAL {{ ?book schema:url ?url . }}
  OPTIONAL {{
    GRAPH <{self.author_graph_uri}> {{ ?author schema:name ?authorName . }}
  }}
}}
"""  # noqa: S608 - resource URIs are restricted to the provider prefix
        return query  # noqa: RET504 - separate assignment carries the S608 justification


def _test_dbnl_connection() -> dict[str, Any]:
    return test_kb_connection(DbnlProvider())


@register_settings("dbnl", "DBNL", icon="book", order=55, group="metadata_providers")
def dbnl_settings() -> list[SettingsField]:
    """DBNL metadata provider settings."""
    return [
        HeadingField(
            key="dbnl_heading",
            title="Digitale Bibliotheek voor de Nederlandse Letteren",
            description=(
                "Specialist source for Dutch and Flemish literary classics and historical "
                "editions. Free, public, and no API key required."
            ),
            link_url=DbnlProvider.website_url,
            link_text="data.bibliotheken.nl",
        ),
        CheckboxField(
            key="DBNL_ENABLED",
            label="Enable DBNL",
            description="Use DBNL as a specialist metadata provider for Dutch literature.",
            default=False,
        ),
        ActionButton(
            key="test_connection",
            label="Test Connection",
            description="Verify the public DBNL Linked Data graph is accessible",
            style="primary",
            callback=_test_dbnl_connection,
        ),
    ]
