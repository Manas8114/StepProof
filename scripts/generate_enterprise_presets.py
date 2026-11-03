"""Generate 5 standard enterprise procedure artifacts in data/procedures/ out of the box:
1. stripe_refund.json (Dispute resolution & partial refund)
2. github_issue_restock.json (Warehouse inventory restock issue creation)
3. google_forms_submission.json (Employee equipment onboarding survey)
4. salesforce_lead_update.json (Enterprise CRM lead update with shadow-piercing locators)
5. expense_compliance_audit.json (ACME compliance expense audit & approval)

Each procedure is cryptographically signed and carries multi-locators, vision concepts,
parameters, and deterministic success checks.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stepproof.proc import Procedure, Step, Locator

def generate_all_presets():
    d = Path(__file__).resolve().parent.parent / "data" / "procedures"
    d.mkdir(parents=True, exist_ok=True)

    # 1. Stripe Refund
    p1 = Procedure(
        goal="Stripe partial refund verification and customer dispute settlement",
        site="https://dashboard.stripe.com/payments",
        steps=[
            Step(id="s1", description="Type charge ID into search filter", action="type",
                 arg={"text": "ch_3N19876251"},
                 locators=[Locator("css", "input[data-test='search-input']"), Locator("role", "textbox Search payments"), Locator("box", "180,45")],
                 vision_concept="Payment search input"),
            Step(id="s2", description="Click payment transaction row", action="click",
                 arg={},
                 locators=[Locator("css", "tr[data-test='payment-row']"), Locator("role", "row ch_3N19876251"), Locator("box", "400,160")],
                 vision_concept="Payment transaction row"),
            Step(id="s3", description="Click Refund payment button", action="click",
                 arg={},
                 locators=[Locator("css", "button[data-test='refund-button']"), Locator("role", "button Refund"), Locator("box", "820,95")],
                 vision_concept="Refund payment button"),
            Step(id="s4", description="Type refund amount into amount input", action="type",
                 arg={"text": "25.00"},
                 locators=[Locator("css", "input[name='refund_amount']"), Locator("role", "textbox Refund amount"), Locator("box", "512,320")],
                 vision_concept="Refund amount number input"),
            Step(id="s5", description="Select refund reason dropdown", action="select",
                 arg={"value": "Customer dispute resolution"},
                 locators=[Locator("css", "select[name='reason']"), Locator("role", "combobox Reason for refund"), Locator("box", "512,380")],
                 vision_concept="Refund reason dropdown"),
            Step(id="s6", description="Click confirm refund button", action="click",
                 arg={},
                 locators=[Locator("css", "button[data-test='confirm-refund']"), Locator("role", "button Confirm Refund"), Locator("box", "620,440")],
                 vision_concept="Confirm refund button")
        ],
        parameters={"charge_id": "ch_3N19876251", "refund_amount": "25.00", "reason": "Customer dispute resolution"},
        success_checks=[{"kind": "text_visible", "spec": {"text": "Refund issued"}}, {"kind": "text_visible", "spec": {"text": "Status: Refunded"}}],
        source="enterprise_preset"
    )
    p1.sign()
    (d / "stripe_refund.json").write_text(json.dumps(p1.to_dict(), indent=2))

    # 2. GitHub Issue Restock
    p2 = Procedure(
        goal="Automated warehouse inventory restock issue creation",
        site="https://github.com/enterprise-ops/inventory/issues/new",
        steps=[
            Step(id="s1", description="Type issue title for restock", action="type",
                 arg={"text": "Restock WS-1042: Low threshold alert"},
                 locators=[Locator("css", "#issue_title"), Locator("css", "input[name='issue[title]']"), Locator("box", "320,180")],
                 vision_concept="Issue title text input"),
            Step(id="s2", description="Type inventory justification into body textarea", action="type",
                 arg={"text": "Inventory dropped below safe threshold (qty remaining: 12). Urgently request batch restock of 150 units."},
                 locators=[Locator("css", "#issue_body"), Locator("css", "textarea[name='issue[body]']"), Locator("box", "320,300")],
                 vision_concept="Issue body comment textarea"),
            Step(id="s3", description="Click label selector button", action="click",
                 arg={},
                 locators=[Locator("css", "button[data-hotkey='l']"), Locator("role", "button Labels"), Locator("box", "880,180")],
                 vision_concept="Labels selector button"),
            Step(id="s4", description="Click restock label checkbox", action="click",
                 arg={},
                 locators=[Locator("css", "input[value='restock']"), Locator("role", "checkbox restock"), Locator("box", "880,220")],
                 vision_concept="Restock label option"),
            Step(id="s5", description="Click Submit new issue button", action="click",
                 arg={},
                 locators=[Locator("css", "button.btn-primary[type='submit']"), Locator("role", "button Submit new issue"), Locator("box", "880,420")],
                 vision_concept="Submit new issue button")
        ],
        parameters={"sku": "WS-1042", "qty_needed": "150", "priority": "High"},
        success_checks=[{"kind": "text_visible", "spec": {"text": "Restock WS-1042"}}, {"kind": "text_visible", "spec": {"text": "Open"}}],
        source="enterprise_preset"
    )
    p2.sign()
    (d / "github_issue_restock.json").write_text(json.dumps(p2.to_dict(), indent=2))

    # 3. Google Forms Submission
    p3 = Procedure(
        goal="Employee equipment onboarding survey form submission",
        site="https://docs.google.com/forms/d/e/1FAIpQLSc-onboarding/viewform",
        steps=[
            Step(id="s1", description="Type employee name", action="type",
                 arg={"text": "Jordan Lee"},
                 locators=[Locator("css", "div[role='listitem']:nth-child(1) input"), Locator("role", "textbox Your answer"), Locator("box", "380,240")],
                 vision_concept="Employee name text input"),
            Step(id="s2", description="Click department dropdown listbox", action="click",
                 arg={},
                 locators=[Locator("css", "div[role='listitem']:nth-child(2) div[role='listbox']"), Locator("role", "listbox Choose"), Locator("box", "380,340")],
                 vision_concept="Department dropdown menu"),
            Step(id="s3", description="Select Engineering option", action="click",
                 arg={},
                 locators=[Locator("css", "div[role='option'][data-value='Engineering']"), Locator("role", "option Engineering"), Locator("box", "380,410")],
                 vision_concept="Engineering department option"),
            Step(id="s4", description="Select laptop model radio", action="click",
                 arg={},
                 locators=[Locator("css", "div[role='radio'][aria-label*='MacBook Pro']"), Locator("role", "radio MacBook Pro"), Locator("box", "240,510")],
                 vision_concept="MacBook Pro radio button"),
            Step(id="s5", description="Click Submit form button", action="click",
                 arg={},
                 locators=[Locator("css", "div[role='button'][aria-label='Submit']"), Locator("role", "button Submit"), Locator("box", "260,620")],
                 vision_concept="Submit form button")
        ],
        parameters={"employee_name": "Jordan Lee", "department": "Engineering", "laptop_model": "MacBook Pro 16"},
        success_checks=[{"kind": "text_visible", "spec": {"text": "Your response has been recorded"}}],
        source="enterprise_preset"
    )
    p3.sign()
    (d / "google_forms_submission.json").write_text(json.dumps(p3.to_dict(), indent=2))

    # 4. Salesforce Lead Update (with Shadow DOM Piercing)
    p4 = Procedure(
        goal="Enterprise CRM lead qualification and opportunity stage update",
        site="https://enterprise.lightning.force.com/lightning/r/Lead/00Q5f000003ABC/view",
        steps=[
            Step(id="s1", description="Click Edit Lead Status button inside shadow root", action="click",
                 arg={},
                 locators=[Locator("css", "lightning-button-menu >> button.slds-button"), Locator("role", "button Edit Status"), Locator("box", "850,110")],
                 vision_concept="Edit Lead Status button"),
            Step(id="s2", description="Select Qualified from Lead Status combobox inside shadow root", action="type",
                 arg={"text": "Qualified"},
                 locators=[Locator("css", "lightning-combobox >> input.slds-combobox__input"), Locator("role", "combobox Lead Status"), Locator("box", "420,280")],
                 vision_concept="Lead Status combobox input"),
            Step(id="s3", description="Click Rating combobox in custom shadow component", action="click",
                 arg={},
                 locators=[Locator("css", "lightning-combobox[data-name='Rating'] >> button"), Locator("role", "combobox Rating"), Locator("box", "420,360")],
                 vision_concept="Rating combobox button"),
            Step(id="s4", description="Select Hot rating option", action="click",
                 arg={},
                 locators=[Locator("css", "lightning-base-combobox-item[data-value='Hot']"), Locator("role", "option Hot"), Locator("box", "420,440")],
                 vision_concept="Hot rating option"),
            Step(id="s5", description="Click Save lead button inside footer shadow root", action="click",
                 arg={},
                 locators=[Locator("css", "lightning-button[variant='brand'] >> button"), Locator("css", "button.slds-button_brand"), Locator("box", "760,540")],
                 vision_concept="Save lead brand button")
        ],
        parameters={"lead_name": "Acme Industrial Corp", "status": "Qualified", "rating": "Hot"},
        success_checks=[{"kind": "text_visible", "spec": {"text": "Lead Status: Qualified"}}, {"kind": "text_visible", "spec": {"text": "Rating: Hot"}}],
        source="enterprise_preset"
    )
    p4.sign()
    (d / "salesforce_lead_update.json").write_text(json.dumps(p4.to_dict(), indent=2))

    # 5. Expense Compliance Audit
    p5 = Procedure(
        goal="ACME enterprise expense compliance audit and approval flow",
        site="http://localhost:8011/site/expense/",
        steps=[
            Step(id="s1", description="Type vendor name", action="type",
                 arg={"text": "Acme Global"},
                 locators=[Locator("css", "#vendor"), Locator("role", "textbox Vendor"), Locator("box", "320,160")],
                 vision_concept="Vendor text input"),
            Step(id="s2", description="Type amount value", action="type",
                 arg={"text": "142.50"},
                 locators=[Locator("css", "#amount"), Locator("role", "textbox Amount"), Locator("box", "320,220")],
                 vision_concept="Amount number input"),
            Step(id="s3", description="Select travel category", action="select",
                 arg={"value": "travel"},
                 locators=[Locator("css", "#category"), Locator("role", "combobox Category"), Locator("box", "320,280")],
                 vision_concept="Category dropdown menu"),
            Step(id="s4", description="Click Submit expense claim", action="click",
                 arg={},
                 locators=[Locator("css", "#submit"), Locator("css", "button[type='submit']"), Locator("box", "320,350")],
                 vision_concept="Submit claim button")
        ],
        parameters={"vendor": "Acme Global", "amount": "142.50", "category": "travel", "approver": "Finance Director"},
        success_checks=[{"kind": "text_visible", "spec": {"text": "Claim filed"}}, {"kind": "url_contains", "spec": {"url": "expense"}}],
        source="enterprise_preset"
    )
    p5.sign()
    (d / "expense_compliance_audit.json").write_text(json.dumps(p5.to_dict(), indent=2))

    return [p1, p2, p3, p4, p5]

if __name__ == "__main__":
    procs = generate_all_presets()
    print(f"Generated and signed {len(procs)} enterprise procedure templates in data/procedures/")
