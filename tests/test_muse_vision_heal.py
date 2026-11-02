"""Unit tests for MuseVisionHealer (offline, mocked OpenAI Responses client)."""
import json
from unittest.mock import MagicMock
from stepproof.browser.vision_heal import MuseVisionHealer, LOCATE_TOOL


def _mock_response(args=None, name="locate_element", has_call=True):
    resp = MagicMock()
    if has_call:
        item = MagicMock()
        item.type = "function_call"
        item.name = name
        item.arguments = json.dumps(args) if isinstance(args, dict) else args
        resp.output = [item]
    else:
        resp.output = []
    return resp


def test_muse_healer_grounding_success():
    healer = MuseVisionHealer(min_confidence=0.6)
    healer.client = MagicMock()
    healer.client.responses.create.return_value = _mock_response(
        {"x": 100, "y": 200, "w": 50, "h": 20, "confidence": 0.9}
    )

    res = healer.heal("data:image/jpeg;base64,abc", "Submit button")
    assert res is not None
    assert res["x"] == 125
    assert res["y"] == 210
    assert res["grounded_by"] == "muse"
    assert res["conf"] == 0.9

    # Verify tool_choice is "auto"
    kwargs = healer.client.responses.create.call_args.kwargs
    assert kwargs["tool_choice"] == "auto"
    assert kwargs["tools"] == [LOCATE_TOOL]


def test_muse_healer_low_confidence_filtered():
    healer = MuseVisionHealer(min_confidence=0.7)
    healer.client = MagicMock()
    healer.client.responses.create.return_value = _mock_response(
        {"x": 100, "y": 200, "w": 50, "h": 20, "confidence": 0.4}
    )

    res = healer.heal("data:image/jpeg;base64,abc", "Submit button")
    assert res is None


def test_muse_healer_confidence_zero_or_no_box():
    healer = MuseVisionHealer(min_confidence=0.5)
    healer.client = MagicMock()
    # Confidence 0
    healer.client.responses.create.return_value = _mock_response(
        {"x": 0, "y": 0, "w": 0, "h": 0, "confidence": 0.0}
    )
    assert healer.heal("data:image/jpeg;base64,abc", "Missing button") is None

    # Zero width/height
    healer.client.responses.create.return_value = _mock_response(
        {"x": 100, "y": 100, "w": 0, "h": 10, "confidence": 0.9}
    )
    assert healer.heal("data:image/jpeg;base64,abc", "Zero box") is None


def test_muse_healer_no_tool_call():
    healer = MuseVisionHealer()
    healer.client = MagicMock()
    healer.client.responses.create.return_value = _mock_response(has_call=False)
    assert healer.heal("data:image/jpeg;base64,abc", "Button") is None
