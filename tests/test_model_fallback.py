"""Model-404 fallback (AGENT_PROMPT rule 5: disclose substitutions). A 404 from the
primary model retries the SAME call on the configured fallback and reports which model
actually answered; any other error is re-raised unchanged (no silent downgrade)."""
import httpx
import pytest
from openai import APIStatusError


class _FakeResp:
    """A stand-in for a successful response. `output` mirrors the shape the callers
    iterate (`_extract_action`); empty list = a graceful no-action result."""
    output = []


def _api_error(status: int) -> APIStatusError:
    """A real APIStatusError carrying an httpx.Response with the given status code."""
    resp = httpx.Response(status, request=httpx.Request("POST", "https://api.meta.ai/v1"))
    return APIStatusError(message="err", response=resp, body=None)


class _FakeClient:
    """Mimics the OpenAI client: 404s on the primary model, succeeds on the fallback."""

    def __init__(self, fail_model="muse-spark-1.3", ok_model="muse-spark-1.1"):
        self.fail_model, self.ok_model = fail_model, ok_model
        self.calls = []

    def responses_create(self, model, **kwargs):
        self.calls.append(model)
        if model == self.fail_model:
            raise _api_error(404)
        if model == self.ok_model:
            return _FakeResp()
        raise AssertionError(f"unexpected model {model}")

    # duck-type the attribute the helper uses
    @property
    def responses(self):
        class _R:
            def __init__(self, c):
                self._c = c

            def create(self, model, **kw):
                return self._c.responses_create(model, **kw)
        return _R(self)


def test_404_falls_back_and_reports_model_used(monkeypatch):
    monkeypatch.setattr("stepproof.config.MUSE_FALLBACK_MODEL", "muse-spark-1.1")
    import stepproof.model_fallback as mf
    c = _FakeClient()
    resp, used, fell_back = mf.responses_with_fallback(c, "muse-spark-1.3", input=[], tools=[])
    assert fell_back is True and used == "muse-spark-1.1"
    assert resp is not None and c.calls == ["muse-spark-1.3", "muse-spark-1.1"]


def test_non_404_error_is_re_raised_not_downgraded(monkeypatch):
    monkeypatch.setattr("stepproof.config.MUSE_FALLBACK_MODEL", "muse-spark-1.1")
    import stepproof.model_fallback as mf

    class _C500(_FakeClient):
        def responses_create(self, model, **kw):
            self.calls.append(model)
            raise _api_error(500)

    with pytest.raises(APIStatusError):
        mf.responses_with_fallback(_C500(), "muse-spark-1.3", input=[], tools=[])


def test_success_never_calls_fallback(monkeypatch):
    monkeypatch.setattr("stepproof.config.MUSE_FALLBACK_MODEL", "muse-spark-1.1")
    import stepproof.model_fallback as mf
    c = _FakeClient()

    class _AlwaysOk(_FakeClient):
        def responses_create(self, model, **kw):
            self.calls.append(model)
            return _FakeResp()

    oc = _AlwaysOk()
    resp, used, fell_back = mf.responses_with_fallback(oc, "muse-spark-1.3", input=[], tools=[])
    assert fell_back is False and used == "muse-spark-1.3"
    assert oc.calls == ["muse-spark-1.3"]


def test_agent_model_decide_discloses_fallback(monkeypatch):
    """decide() falls back on a 404 and records it, so /api/v2/health can disclose the
    substitution instead of hiding it."""
    monkeypatch.setattr("stepproof.config.MUSE_FALLBACK_MODEL", "muse-spark-1.1")
    monkeypatch.setattr("stepproof.agent.model.cfg.VISION_MODEL", "muse-spark-1.3")
    from stepproof.agent.model import MuseAgentModel

    m = MuseAgentModel.__new__(MuseAgentModel)   # skip OpenAI client construction
    m.client = _FakeClient()                    # 404s on primary, ok on fallback
    m.calls = 0
    m.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    m.active_model, m.fell_back = "muse-spark-1.3", False

    act = m.decide("do something", "obs", "data:image/jpeg;base64,", [])
    # the fallback response has no function call -> None (the loop turns that into finish);
    # the point of the test is the DISCLOSURE state, not the action
    assert act is None                          # graceful, no crash
    assert m.fell_back is True and m.active_model == "muse-spark-1.1"
    assert m.client.calls == ["muse-spark-1.3", "muse-spark-1.1"]
