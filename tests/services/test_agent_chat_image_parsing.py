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
    wrapped = '```json\n{"plant_name":"Rose","species":"Rosa","note":"Sun"}\n```'
    extracted = LangGraphChatAgent._extract_json_object(wrapped)
    assert extracted == '{"plant_name":"Rose","species":"Rosa","note":"Sun"}'


def test_parse_not_detected_truthy_string_marker() -> None:
    payload = LangGraphChatAgent._parse_vision_payload('{"not_detected":"true"}')
    assert payload is not None
    assert LangGraphChatAgent._is_not_detected_payload(payload) is True


def test_extract_text_field_supports_fallback_keys() -> None:
    payload = {"common_name": "Snake Plant", "botanical_name": "Dracaena trifasciata"}
    assert LangGraphChatAgent._extract_text_field(payload, "plant_name", "common_name") == "Snake Plant"
    assert LangGraphChatAgent._extract_text_field(payload, "species", "botanical_name") == "Dracaena trifasciata"


def test_detect_plant_sets_provider_error_on_empty_model_response() -> None:
    agent = LangGraphChatAgent()
    agent._vision_enabled = True
    agent._vision_llm = None
    agent._invoke_vision_openrouter_rest = lambda _prompt, _data_url: ""

    detected = agent._detect_plant("dGVzdA==dGVzdA==dGVzdA==dGVzdA==")

    assert detected is None
    assert agent._last_plant_image_failure_reason == "provider_error"
