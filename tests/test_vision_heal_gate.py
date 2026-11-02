"""Unit tests for T5: Gating healed actions (code-first safety).

Tests assert:
1. A vision-healed click on a Submit/Discard-class target is blocked without approval.
2. A vision-healed click on a Submit/Discard-class target executes when approved.
3. An unresolvable label escalates to approval (treated as irreversible/external).
"""
from unittest.mock import MagicMock
from stepproof.proc import Step, Procedure, Locator
from stepproof.agent.executor import execute_procedure


def test_vision_healed_submit_blocked_without_approval():
    tb = MagicMock()
    tb.observe.return_value = {"url": "http://127.0.0.1:8000/site/expense/"}

    def mock_act(op, arg=None):
        if op == "click_sel":
            raise RuntimeError("Selector broken")
        if op == "eval":
            return "Submit claim"
        return {"ok": True}
    tb.act.side_effect = mock_act

    step = Step(id="s1", description="file claim", action="click",
                locators=[Locator(kind="css", value="#broken-submit")])
    proc = Procedure(goal="Submit expense", steps=[step])

    vision_mock = MagicMock(return_value={"x": 100, "y": 200, "grounded_by": "sam"})

    # Denying approval
    res = execute_procedure(tb, proc, approve_fn=lambda tool, arg: False, vision_selfheal=vision_mock)
    assert not res.success
    assert "healed target blocked: not approved" in res.error
    assert res.steps_run == 0
    # Ensure click was NOT performed
    for call in tb.act.call_args_list:
        assert call[0][0] != "click_box"


def test_vision_healed_submit_allowed_with_approval():
    tb = MagicMock()
    tb.observe.return_value = {"url": "http://127.0.0.1:8000/site/expense/"}

    def mock_act(op, arg=None):
        if op == "click_sel":
            raise RuntimeError("Selector broken")
        if op == "eval":
            return "Submit claim"
        if op == "click_box":
            return {"ok": True}
        return {"ok": True}
    tb.act.side_effect = mock_act

    step = Step(id="s1", description="file claim", action="click",
                locators=[Locator(kind="css", value="#broken-submit")])
    proc = Procedure(goal="Submit expense", steps=[step])

    vision_mock = MagicMock(return_value={"x": 100, "y": 200, "grounded_by": "sam"})

    # Allowing approval
    approved_args = []
    def approve_fn(tool, arg):
        approved_args.append(arg)
        return True

    res = execute_procedure(tb, proc, approve_fn=approve_fn, vision_selfheal=vision_mock)
    assert res.steps_run == 1
    assert any(a.get("healed") for a in approved_args)
    assert any(a.get("label") == "Submit claim" for a in approved_args)
    # Ensure click_box was called with healed coords
    tb.act.assert_any_call("click_box", {"x": 100, "y": 200})


def test_vision_healed_discard_blocked_without_approval():
    tb = MagicMock()
    tb.observe.return_value = {"url": "http://127.0.0.1:8000/site/expense/"}

    def mock_act(op, arg=None):
        if op == "click_sel":
            raise RuntimeError("Selector broken")
        if op == "eval":
            return "Discard draft"
        return {"ok": True}
    tb.act.side_effect = mock_act

    step = Step(id="s1", description="reset form", action="click",
                locators=[Locator(kind="css", value="#broken-discard")])
    proc = Procedure(goal="Discard draft", steps=[step])

    vision_mock = MagicMock(return_value={"x": 150, "y": 300, "grounded_by": "muse"})

    res = execute_procedure(tb, proc, approve_fn=lambda tool, arg: False, vision_selfheal=vision_mock)
    assert not res.success
    assert "healed target blocked: not approved" in res.error
    assert res.steps_run == 0


def test_vision_healed_unresolvable_label_escalates():
    tb = MagicMock()
    tb.observe.return_value = {"url": "http://127.0.0.1:8000/site/expense/"}

    def mock_act(op, arg=None):
        if op == "click_sel":
            raise RuntimeError("Selector broken")
        if op == "eval":
            return None  # Unresolvable label
        return {"ok": True}
    tb.act.side_effect = mock_act

    step = Step(id="s1", description="ordinary action", action="click",
                locators=[Locator(kind="css", value="#broken-target")])
    proc = Procedure(goal="Unknown action", steps=[step])

    vision_mock = MagicMock(return_value={"x": 50, "y": 50, "grounded_by": "sam"})

    # Denying approval
    res = execute_procedure(tb, proc, approve_fn=lambda tool, arg: False, vision_selfheal=vision_mock)
    assert not res.success
    assert "healed target blocked: not approved" in res.error

    # Allowing approval
    approved_calls = []
    def approve_allow(tool, arg):
        approved_calls.append(arg)
        return True

    res2 = execute_procedure(tb, proc, approve_fn=approve_allow, vision_selfheal=vision_mock)
    assert res2.steps_run == 1
    assert approved_calls[0].get("label") == "unresolvable"
