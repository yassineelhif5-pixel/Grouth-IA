from apps.core.redaction import MASK, mask_hint, redact, redact_text


def test_nested_secrets_are_masked_and_input_untouched():
    data = {"name": "x", "password": "p", "nested": {"api_key": "k", "list": [{"client_secret": "s", "ok": 1}]},
            "access_token": "t", "refresh_token": None}
    out = redact(data)
    assert out["password"] == MASK and out["nested"]["api_key"] == MASK
    assert out["nested"]["list"][0]["client_secret"] == MASK and out["nested"]["list"][0]["ok"] == 1
    assert out["access_token"] == MASK and out["refresh_token"] is None
    assert data["password"] == "p"  # not mutated


def test_extra_secret_fields():
    assert redact({"verification_token": "v", "foo": "bar"}, ["foo"]) == {"verification_token": MASK, "foo": MASK}


def test_tokens_inside_text_are_removed():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123_-"
    text = f"call failed Authorization: Bearer abc.def.ghi token={jwt}"
    out = redact_text(text)
    assert "abc.def.ghi" not in out and jwt not in out


def test_mask_hint():
    assert mask_hint("sk-1234567890abcd") == "••••abcd"
    assert mask_hint("short") == MASK
