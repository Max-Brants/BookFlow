# ruff: noqa: ANN001, ANN201, S101

import codecs

import pytest
from kobo_patcher.conf import OFFICIAL_KOBO_ENDPOINT, ConfError, KoboConf


def test_changes_only_value_and_preserves_bom_comments_and_crlf():
    original = codecs.BOM_UTF8 + (
        b"[General]\r\nname = reader\r\n[OneStoreServices]\r\n"
        b"  api_endpoint = https://old.example  ; retain this\r\nunknown=value\r\n"
    )
    document = KoboConf.from_bytes(original)
    document.set_endpoint("https://new.example/api/kobo/a")
    assert document.to_bytes() == codecs.BOM_UTF8 + (
        b"[General]\r\nname = reader\r\n[OneStoreServices]\r\n"
        b"  api_endpoint = https://new.example/api/kobo/a  ; retain this\r\nunknown=value\r\n"
    )


def test_adds_missing_endpoint_inside_existing_section():
    document = KoboConf.from_bytes(b"[OneStoreServices]\nother=x\n[Other]\na=b\n")
    document.set_endpoint("https://new.example/api/kobo/a")
    assert (
        document.to_bytes()
        == b"[OneStoreServices]\nother=x\napi_endpoint=https://new.example/api/kobo/a\n[Other]\na=b\n"
    )


def test_official_restore_can_add_missing_section():
    document = KoboConf.from_bytes(b"[General]\nfoo=bar\n")
    document.set_endpoint(OFFICIAL_KOBO_ENDPOINT)
    assert document.endpoint() == OFFICIAL_KOBO_ENDPOINT
    assert (
        document.to_bytes()
        == b"[General]\nfoo=bar\n[OneStoreServices]\napi_endpoint=https://storeapi.kobo.com\n"
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"[OneStoreServices]\na=1\n[onestoreservices]\nb=2\n",
        b"[OneStoreServices]\napi_endpoint=a\napi_endpoint=b\n",
    ],
)
def test_refuses_ambiguous_target(payload):
    with pytest.raises(ConfError):
        KoboConf.from_bytes(payload).endpoint()


def test_utf16_is_preserved():
    raw = codecs.BOM_UTF16_LE + "[OneStoreServices]\r\napi_endpoint=old\r\n".encode("utf-16-le")
    document = KoboConf.from_bytes(raw)
    document.set_endpoint("https://new.example/api/kobo/token")
    assert document.to_bytes().startswith(codecs.BOM_UTF16_LE)
    assert (
        KoboConf.from_bytes(document.to_bytes()).endpoint() == "https://new.example/api/kobo/token"
    )
