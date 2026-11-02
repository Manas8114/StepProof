"""Unit tests for T3 visual fill (actions routing + password protection in fill_at)."""
import pytest
from unittest.mock import MagicMock
from stepproof.browser.actions import execute_action
from stepproof.proc import Step, Procedure, Locator
from stepproof.agent.executor import execute_procedure


def test_visual_fill_action_routing():
    tb = MagicMock()
    tb.observe.return_value = {"url": "http://127.0.0.1:8000/site/expense/"}
    tb.act.return_value = {"ok": True}

    res = execute_action(tb, "type", {"x": 150, "y": 250, "text": "Acme Corp", "grounded_by": "sam"})
    assert res.ok
    assert "typed into @(150,250) (sam healed)" in res.detail
    tb.act.assert_called_with("fill_at", {"x": 150, "y": 250, "text": "Acme Corp", "enter": False})


def test_visual_fill_failure_handling():
    tb = MagicMock()
    tb.observe.return_value = {"url": "http://127.0.0.1:8000/site/expense/"}
    tb.act.return_value = {"ok": False, "error": "refusing to type into password field"}

    res = execute_action(tb, "type", {"x": 150, "y": 250, "text": "secret123"})
    assert not res.ok
    assert "refusing to type into password field" in res.detail


def test_executor_merges_text_into_healed_arg():
    tb = MagicMock()
    tb.observe.return_value = {"url": "http://127.0.0.1:8000/site/expense/"}

    def mock_act(op, arg=None):
        if op == "fill":
            raise RuntimeError("Selector broken")
        if op == "fill_at":
            return {"ok": True}
        return {"ok": True}
    tb.act.side_effect = mock_act

    step = Step(id="s1", description="Vendor", action="type", arg={"text": "Acme Corp"},
                locators=[Locator(kind="css", value="#broken-vendor")])
    proc = Procedure(goal="Test fill heal", steps=[step])

    # Locator fails, vision heal returns box coords
    vision_mock = MagicMock(return_value={"x": 120, "y": 240, "grounded_by": "muse"})

    res = execute_procedure(tb, proc, vision_selfheal=vision_mock)
    assert res.steps_run == 1
    assert any("vision healed" in s.get("note", "") for s in res.healed_steps)
    tb.act.assert_any_call("fill_at", {"x": 120, "y": 240, "text": "Acme Corp", "enter": False})


def test_session_fill_at_refuses_password():
    from stepproof.browser.session import TinyBrowser
    tb = TinyBrowser(allowlist={"127.0.0.1"})
    try:
        html = ("<input id='user' type='text' style='position:absolute;left:10px;top:10px;width:100px;height:30px'>"
                "<input id='pass' type='password' style='position:absolute;left:10px;top:60px;width:100px;height:30px'>")
        tb.act("eval", {"expr": f"document.body.innerHTML = {repr(html)}"})

        # Try to fill password field (or masked field at those coordinates)
        r_pass = tb.fill_at(20, 70, "secret")
        assert not r_pass.get("ok")
        assert "refusing" in r_pass.get("error", "")

        # Normal text field succeeds
        r_user = tb.fill_at(20, 20, "alice")
        assert r_user.get("ok")
        val = tb.act("eval", {"expr": "document.getElementById('user').value"})
        assert val == "alice"
    finally:
        tb.stop()
