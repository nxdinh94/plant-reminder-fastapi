from app.services.agent_chat import LangGraphChatAgent


def test_normalize_data_url_with_whitespace_and_urlsafe_chars() -> None:
    data_url = "data:image/png;base64,aGVs bG8td29ybGQ_"
    normalized = LangGraphChatAgent._normalize_to_data_url(data_url)
    assert normalized is not None
    assert normalized.startswith("data:image/png;base64,")
    assert " " not in normalized
    assert "_" not in normalized
    assert "-" not in normalized


def test_normalize_raw_base64_without_padding() -> None:
    raw = "aGVsbG8"  # "hello" without trailing padding
    normalized = LangGraphChatAgent._normalize_to_data_url(raw)
    assert normalized == "data:image/jpeg;base64,aGVsbG8="


def test_normalize_rejects_invalid_payload() -> None:
    assert LangGraphChatAgent._normalize_to_data_url("not-valid-@@@") is None


def test_extract_json_object_from_markdown_wrapped_reply() -> None:
    wrapped = '```json\n{"plant_name":"Rose","species":"Rosa","short_care_guide":"Sun"}\n```'
    extracted = LangGraphChatAgent._extract_json_object(wrapped)
    assert extracted == '{"plant_name":"Rose","species":"Rosa","short_care_guide":"Sun"}'
