"""P2 never-cut: Advisor A "is this file important?" (pre-delete check). The verdict + risk
class are DECIDED BY DETERMINISTIC CODE from the gathered signals - a model may phrase the
explanation but can never set the risk class or waive a rule. Adversarial fixture cases:
secret files, regenerable build dirs, duplicates, open files, git-tracked source, and
'looks-temp but is a user document' (must NOT be called safe without a duplicate)."""
from pathlib import Path

from companion.advisor_a import assess_delete, risk_class_for, is_reversible_action


def test_secret_file_is_high_risk_keep():
    a = assess_delete({"path": "C:/proj/.env", "location": "project", "ext": ".env",
                       "name": ".env", "is_secret": True, "is_regenerable": False,
                       "is_duplicate": False, "open_handles": 0, "git": "tracked"})
    assert a.risk == "high" and a.verdict == "keep"
    assert a.reasons, "a high-risk keep must always carry an evidence reason"


def test_regenerable_build_dir_is_likely_safe_low():
    a = assess_delete({"path": "node_modules/x", "location": "project", "ext": "",
                       "is_regenerable": True, "is_secret": False,
                       "is_duplicate": False, "open_handles": 0, "git": "ignored"})
    assert a.verdict == "likely_safe" and a.risk == "low"


def test_duplicate_temp_is_safe_low():
    a = assess_delete({"path": "C:/tmp/cache/a.bin", "location": "temp", "ext": ".bin",
                       "is_duplicate": True, "is_secret": False, "open_handles": 0, "git": ""})
    assert a.verdict == "safe" and a.risk == "low"


def test_open_file_is_review_never_auto_delete():
    a = assess_delete({"path": "C:/docs/report.docx", "location": "documents", "ext": ".docx",
                       "is_secret": False, "is_regenerable": False, "is_duplicate": False,
                       "open_handles": 2, "git": ""})
    assert a.verdict == "review" and a.risk == "medium"
    assert "open" in " ".join(a.reasons).lower()


def test_user_document_never_safe_without_evidence():
    """A user document with no duplicate/backup must NOT be 'safe' even if it lives in a
    downloads folder - the spec's hard rule: never say 'safe' for a user document
    without evidence of a duplicate or backup."""
    a = assess_delete({"path": "C:/Users/me/Downloads/tax-2025.pdf", "location": "downloads",
                       "ext": ".pdf", "is_secret": False, "is_regenerable": False,
                       "is_duplicate": False, "open_handles": 0, "git": ""})
    assert a.verdict in ("keep", "review") and a.risk != "low"


def test_git_tracked_source_is_review():
    a = assess_delete({"path": "src/core.py", "location": "project", "ext": ".py",
                       "is_regenerable": False, "is_duplicate": False, "open_handles": 0,
                       "git": "tracked"})
    assert a.verdict == "review" and "git" in " ".join(r.lower() for r in a.reasons)


def test_risk_class_is_code_not_model():
    """The risk class comes from deterministic signals only - there is no model input."""
    assert risk_class_for({"is_secret": True}) == "high"
    assert risk_class_for({"open_handles": 1, "location": "documents"}) == "medium"
    assert risk_class_for({"is_duplicate": True}) == "low"


def test_action_is_reversible_not_permanent_delete():
    """Any delete action the advisor can propose MUST be reversible (trash), never a
    permanent os.remove; and it is dry-run first + audit-logged."""
    assert is_reversible_action("trash")
    assert not is_reversible_action("rm")
    assert not is_reversible_action("os.remove")


def test_adversarial_secret_in_temp_still_high(tmp_path: Path):
    """A 'secret' file dropped in a temp folder is still high risk - location must not
    downgrade a credential pattern."""
    p = tmp_path / "keys" / "id_rsa"
    p.parent.mkdir(parents=True)
    p.write_text("secret material")
    a = assess_delete({"path": str(p), "location": "temp", "ext": "", "name": "id_rsa",
                       "is_secret": True, "is_duplicate": False, "open_handles": 0, "git": ""})
    assert a.risk == "high" and a.verdict == "keep"
