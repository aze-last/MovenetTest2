import numpy as np
from monitor_app import cloud_verifier as cv


def test_payload_builder_openai_shape():
    p = cv.build_chat_payload("vendor/model", "Knife (90%)", "MEDIUM", "data:image/jpeg;base64,AAA")
    assert p["model"] == "vendor/model"
    msg = p["messages"][0]
    kinds = {c["type"] for c in msg["content"]}
    assert kinds == {"text", "image_url"}
    assert "strict JSON" in msg["content"][0]["text"]


def test_parse_model_text_valid_and_garbage():
    ok = cv.CloudVerifier._parse_model_text('{"verdict":"confirm","reason":"knife visible","caption":"man holding phone"}')
    assert ok["verdict"] == "confirm"
    bad = cv.CloudVerifier._parse_model_text("not json at all")
    assert bad["verdict"] == "unsure"


def test_verify_async_noop_when_disabled():
    # Default config.yaml has enabled:false -> must not spawn network, returns False
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    v = cv.get_cloud_verifier()
    assert v.verify_async("0", "INC_test", "Knife", "MEDIUM", frame) is False


def test_https_guard_rejects_http():
    assert cv._is_allowed_https_url("https://api.xkiro.com/v1") is True
    assert cv._is_allowed_https_url("http://api.xkiro.com/v1") is False
