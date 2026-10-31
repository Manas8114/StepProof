from stepproof.rules import Params, evaluate, overall
from stepproof.schemas import Detection, ProcedureSpec, StateCheck, Step

N, FPS = 100, 10.0
P = Params(stable_frames=5)


def dets(frames, conf=0.9, count=1):
    return [Detection(frame=f, obj_id=i, box=(0, 0, 5, 5), conf=conf) for f in frames for i in range(count)]


def spec(*steps):
    return ProcedureSpec(name="t", steps=list(steps))


def run(sp, d, state_fn=None):
    return {r.step_id: r for r in evaluate(sp, d, FPS, N, state_fn, P)}


def test_pass_and_timestamp():
    r = run(spec(Step(id="s1", description="", concept="connector")), {"connector": dets(range(10, 100))})["s1"]
    assert r.verdict == "pass" and r.first_frame == 10 and r.first_time_s == 1.0


def test_never_seen_fails():
    assert run(spec(Step(id="s1", description="", concept="connector")), {})["s1"].verdict == "fail"


def test_min_count_two_with_one_detection_fails():
    r = run(spec(Step(id="s1", description="", concept="screw", min_count=2)), {"screw": dets(range(100), count=1)})["s1"]
    assert r.verdict == "fail"


def test_must_still_hold_at_end_unless_persist_false():
    d = {"connector": dets(range(10, 40))}
    assert run(spec(Step(id="s1", description="", concept="connector")), d)["s1"].verdict == "fail"
    assert run(spec(Step(id="s1", description="", concept="connector", persist=False)), d)["s1"].verdict == "pass"


def test_flicker_goes_to_review():
    r = run(spec(Step(id="s1", description="", concept="connector")), {"connector": dets(range(0, 100, 2))})["s1"]
    assert r.verdict == "review"


def test_low_confidence_goes_to_review():
    r = run(spec(Step(id="s1", description="", concept="connector")), {"connector": dets(range(10, 100), conf=0.6)})["s1"]
    assert r.verdict == "review"


def test_order_violation_fails_and_correct_order_passes():
    sp = spec(Step(id="s1", description="", concept="connector"), Step(id="s2", description="", concept="cover", after=["s1"]))
    bad = run(sp, {"connector": dets(range(50, 100)), "cover": dets(range(10, 100))})
    assert bad["s1"].verdict == "pass" and bad["s2"].verdict == "fail"
    good = run(sp, {"connector": dets(range(10, 100)), "cover": dets(range(50, 100))})
    assert overall(list(good.values())) == "pass"
    tie = run(sp, {"connector": dets(range(10, 100)), "cover": dets(range(10, 100))})
    assert tie["s2"].verdict == "review"


def test_missing_prerequisite_means_dependent_needs_review():
    sp = spec(Step(id="s1", description="", concept="connector"), Step(id="s2", description="", concept="cover", after=["s1"]))
    r = run(sp, {"cover": dets(range(10, 100))})
    assert r["s1"].verdict == "fail" and r["s2"].verdict == "review"


def test_state_check_no_fails_uncertain_reviews_yes_passes():
    sp = spec(Step(id="s1", description="", concept="lid", state_question="Is the lid closed?"))
    d = {"lid": dets(range(10, 100))}
    def mk(a, c=0.95): return lambda step, frame: StateCheck(answer=a, confidence=c, rationale="x")
    assert run(sp, d, mk("no"))["s1"].verdict == "fail"
    assert run(sp, d, mk("uncertain"))["s1"].verdict == "review"
    assert run(sp, d, mk("yes", 0.5))["s1"].verdict == "review"
    assert run(sp, d, mk("yes"))["s1"].verdict == "pass"
