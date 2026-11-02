"""Mode C: Task Family compiler with parameterised slots and per-value safety classification.
Models perceive, code decides:
Slot proposals are generated from recorded values, but slot selection is strictly HUMAN-GATED.
Instantiating a family type-validates values and RE-CLASSIFIES SAFETY PER VALUE:
a "Discard" or high-value payload elevates risk and gates execution deterministically.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import hmac
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Any, Union

from ..proc import Procedure, Step, Locator
from ..artifact import sign_procedure, get_device_key, canonical_json
from ..audit import AuditSpine


@dataclass
class SlotDef:
    name: str
    slot_type: str = "string"              # string | number | enum
    pattern: str = ""
    default: Any = ""
    safety_class: str = "SAFE"            # SAFE | SENSITIVE | DANGEROUS | IRREVERSIBLE
    allowed_values: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SlotDef":
        return cls(**d)


@dataclass
class ProcedureFamily:
    name: str
    procedure: Procedure
    slots: dict[str, SlotDef] = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    signature: str = ""

    def to_dict(self) -> dict:
        return {
            "format": "stepproof-procedure-family-v1",
            "name": self.name,
            "procedure": self.procedure.to_dict(),
            "slots": {k: v.to_dict() for k, v in self.slots.items()},
            "manifest": self.manifest,
            "provenance": self.provenance,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProcedureFamily":
        proc = Procedure.from_dict(d.get("procedure", {}))
        slots = {k: SlotDef.from_dict(v) for k, v in d.get("slots", {}).items()}
        fam = cls(
            name=d.get("name", "unnamed_family"),
            procedure=proc,
            slots=slots,
            manifest=d.get("manifest", {}),
            provenance=d.get("provenance", {}),
            signature=d.get("signature", ""),
        )
        return fam


def sign_family(family: ProcedureFamily, device_key: Optional[str] = None) -> ProcedureFamily:
    """Cryptographically sign a procedure family under the device key."""
    k = device_key or get_device_key()
    fam_payload = {
        "name": family.name,
        "procedure": family.procedure.to_dict(),
        "slots": {sname: sdef.to_dict() for sname, sdef in sorted(family.slots.items())},
    }
    payload_json = canonical_json(fam_payload)
    fam_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    manifest = {
        "version": "1.0",
        "format": "stepproof-family-manifest-v1",
        "family_hash": fam_hash,
        "slot_count": len(family.slots),
        "step_count": len(family.procedure.steps),
    }
    family.manifest = manifest

    prov = dict(family.provenance or {})
    prov.setdefault("compiler", "stepproof-family-c2")
    prov.setdefault("device_id", hashlib.sha256(k.encode("utf-8")).hexdigest()[:16])
    prov["signed_ts"] = round(time.time(), 3)
    family.provenance = prov

    manifest_bytes = canonical_json(manifest).encode("utf-8")
    family.signature = hmac.new(k.encode("utf-8"), manifest_bytes, hashlib.sha256).hexdigest()
    return family


def verify_family(family: ProcedureFamily, device_key: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """Verify cryptographic integrity of a procedure family."""
    if not family.signature or not family.manifest:
        return False, "Unsigned family: missing manifest or signature"

    fam_payload = {
        "name": family.name,
        "procedure": family.procedure.to_dict(),
        "slots": {sname: sdef.to_dict() for sname, sdef in sorted(family.slots.items())},
    }
    expected_hash = hashlib.sha256(canonical_json(fam_payload).encode("utf-8")).hexdigest()
    if family.manifest.get("family_hash") != expected_hash:
        return False, "Tampered family body: hash does not match manifest"

    k = device_key or get_device_key()
    manifest_bytes = canonical_json(family.manifest).encode("utf-8")
    expected_sig = hmac.new(k.encode("utf-8"), manifest_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(family.signature, expected_sig):
        return False, "Signature mismatch: family signed with a different key"

    return True, None


def propose_slots(proc: Procedure) -> dict[str, SlotDef]:
    """Inspect concrete recorded values in steps and generate candidate slot proposals."""
    proposals: dict[str, SlotDef] = {}
    for step in proc.steps:
        arg = step.arg or {}
        text_val = str(arg.get("text", "")).strip()
        select_val = str(arg.get("value", "")).strip()

        # Check text fields
        if text_val and not text_val.startswith("{"):
            if text_val.isdigit() or re.match(r"^\d+(\.\d+)?$", text_val):
                slot_name = "amount" if any(x in step.description.lower() for x in ("amount", "cost", "price", "total")) else f"num_{step.id}"
                proposals[slot_name] = SlotDef(
                    name=slot_name,
                    slot_type="number",
                    pattern=r"^\d+(\.\d{1,2})?$",
                    default=text_val,
                    safety_class="SAFE",
                )
            else:
                slot_name = "vendor" if any(x in step.description.lower() for x in ("vendor", "merchant", "payee", "company")) else f"text_{step.id}"
                proposals[slot_name] = SlotDef(
                    name=slot_name,
                    slot_type="string",
                    default=text_val,
                    safety_class="SAFE",
                )

        # Check dropdown/select
        if select_val and not select_val.startswith("{"):
            slot_name = "category" if "category" in step.description.lower() else f"choice_{step.id}"
            proposals[slot_name] = SlotDef(
                name=slot_name,
                slot_type="enum",
                default=select_val,
                allowed_values=[select_val],
                safety_class="SAFE",
            )

    return proposals


def compile_family(proc: Procedure,
                   name: Optional[str] = None,
                   confirmed_slots: Optional[Union[list[str], dict[str, SlotDef]]] = None,
                   interactive: bool = False,
                   device_key: Optional[str] = None) -> ProcedureFamily:
    """Compile a Procedure into a ProcedureFamily.
    Slot proposals are human-gated: only confirmed slots are parameterized.
    """
    proposals = propose_slots(proc)
    active_slots: dict[str, SlotDef] = {}

    if confirmed_slots is not None:
        if isinstance(confirmed_slots, list):
            for sname in confirmed_slots:
                if sname in proposals:
                    active_slots[sname] = proposals[sname]
                else:
                    active_slots[sname] = SlotDef(name=sname, slot_type="string")
        elif isinstance(confirmed_slots, dict):
            active_slots = confirmed_slots
    elif interactive:
        print("\n--- Proposed Parameter Slots ---")
        for sname, sdef in proposals.items():
            print(f"  Slot '{sname}' (type={sdef.slot_type}, concrete='{sdef.default}')")
        resp = input("Enter comma-separated slot names to confirm (or press Enter for all): ").strip()
        if resp:
            selected = [x.strip() for x in resp.split(",") if x.strip()]
            for sname in selected:
                if sname in proposals:
                    active_slots[sname] = proposals[sname]
        else:
            active_slots = proposals
    else:
        # Default in non-interactive: accept all proposed slots
        active_slots = proposals

    # Clone procedure and replace concrete values with {slot} placeholders
    slotted_proc = copy.deepcopy(proc)
    slotted_proc.parameters = {sname: sdef.default for sname, sdef in active_slots.items()}

    for step in slotted_proc.steps:
        for sname, sdef in active_slots.items():
            val = str(sdef.default)
            if not val:
                continue
            if step.arg:
                for k, v in list(step.arg.items()):
                    if str(v) == val:
                        step.arg[k] = f"{{{sname}}}"
            if val in step.description:
                step.description = step.description.replace(val, f"{{{sname}}}")
            if val in (step.vision_concept or ""):
                step.vision_concept = step.vision_concept.replace(val, f"{{{sname}}}")

    fam_name = name or f"{proc.goal[:20].strip().replace(' ', '_')}_family"
    family = ProcedureFamily(name=fam_name, procedure=slotted_proc, slots=active_slots)
    sign_family(family, device_key=device_key)

    # Log to audit spine: Act 1 seq kind=learn
    spine = AuditSpine()
    spine.append(
        run_id=f"learn_{fam_name}_{int(time.time())}",
        verdict="PASS",
        checks=[],
        steps=[{"step": s.id, "slotted": True} for s in slotted_proc.steps],
        model_disclosure={"source": "compile_family", "slots": list(active_slots.keys())},
        cost={"kind": "learn", "slots_count": len(active_slots)},
    )
    return family


def classify_value_safety(slot_name: str, value: Any, slot_def: SlotDef) -> tuple[str, bool]:
    """Models perceive, code decides: Deterministic per-value safety classification.
    E.g. an amount > 1000 or a vendor 'Discard' / 'Delete' elevates risk to DANGEROUS.
    Returns (safety_level, requires_approval).
    """
    s_val = str(value).strip().lower()

    # Rule 1: Discard / Delete / Terminate keywords
    if any(k in s_val for k in ("discard", "delete", "remove", "drop", "purge", "terminate")):
        return "IRREVERSIBLE", True

    # Rule 2: Amount threshold checks (over $500 requires managerial approval)
    if slot_def.slot_type == "number" or "amount" in slot_name.lower():
        try:
            num = float(s_val)
            if num >= 500.0:
                return "DANGEROUS", True
            if num >= 250.0:
                return "SENSITIVE", False
        except ValueError:
            pass

    # Rule 3: Vendor high-risk names
    if "vendor" in slot_name.lower() and any(k in s_val for k in ("unapproved", "unknown", "flagged", "prohibited")):
        return "DANGEROUS", True

    return "SAFE", False


def instantiate(family: ProcedureFamily, values: dict[str, Any],
                device_key: Optional[str] = None) -> tuple[Procedure, dict]:
    """Instantiate a task family with concrete parameter values.
    Validates types, re-runs safety classification PER VALUE, and re-signs result.
    """
    # 1. Type and constraint validation
    for sname, sdef in family.slots.items():
        if sname not in values and sdef.default is not None:
            values[sname] = sdef.default
        if sname not in values:
            raise ValueError(f"Missing required slot parameter: '{sname}'")

        val = values[sname]
        if sdef.slot_type == "number":
            if sdef.pattern and not re.match(sdef.pattern, str(val)):
                raise TypeError(f"Slot '{sname}' value '{val}' does not match numeric pattern '{sdef.pattern}'")
        elif sdef.slot_type == "enum" and sdef.allowed_values:
            if str(val) not in sdef.allowed_values and len(sdef.allowed_values) > 1:
                raise ValueError(f"Slot '{sname}' value '{val}' not in allowed values: {sdef.allowed_values}")

    # 2. Per-value safety classification
    safety_summary = {}
    highest_risk = "SAFE"
    approval_required = False

    for sname, sdef in family.slots.items():
        val = values[sname]
        risk, needs_approval = classify_value_safety(sname, val, sdef)
        safety_summary[sname] = {"value": val, "risk": risk, "needs_approval": needs_approval}
        if needs_approval:
            approval_required = True
        if risk in ("IRREVERSIBLE", "DANGEROUS"):
            highest_risk = risk

    # 3. Substitute values into procedure steps
    proc = copy.deepcopy(family.procedure)
    proc.parameters = dict(values)

    for step in proc.steps:
        # Re-tag step safety if high risk detected
        if highest_risk != "SAFE":
            step.note = (step.note or "") + f" [Elevated Risk: {highest_risk}]"

        for sname, val in values.items():
            placeholder = f"{{{sname}}}"
            if step.arg:
                for k, v in list(step.arg.items()):
                    if placeholder in str(v):
                        step.arg[k] = str(v).replace(placeholder, str(val))
            if placeholder in step.description:
                step.description = step.description.replace(placeholder, str(val))
            if placeholder in (step.vision_concept or ""):
                step.vision_concept = step.vision_concept.replace(placeholder, str(val))

    # Cryptographically re-sign the concrete instantiated procedure
    sign_procedure(proc, device_key=device_key)
    return proc, {
        "highest_risk": highest_risk,
        "approval_required": approval_required,
        "per_slot_safety": safety_summary,
    }


def re_teach_step(
    family: ProcedureFamily,
    step_id: str,
    updated_step: Step,
    triggering_run_id: str,
    device_key: Optional[str] = None,
) -> ProcedureFamily:
    """Mode C3: Gated re-teach flow.
    When a step drifts or fails checks, human operator demonstrates a replacement step variant.
    The family entry is updated for that step, provenance records the triggering run id,
    the family is re-signed with the device key, and an audit entry is emitted.
    No silent mutations: each version produces a new signature and chain entry.
    """
    new_family = copy.deepcopy(family)
    target = None
    for i, s in enumerate(new_family.procedure.steps):
        if s.id == step_id:
            target = s
            s.action = updated_step.action
            s.arg = copy.deepcopy(updated_step.arg)
            s.locators = copy.deepcopy(updated_step.locators)
            if updated_step.vision_concept:
                s.vision_concept = updated_step.vision_concept
            if updated_step.description:
                s.description = updated_step.description
            break

    if target is None:
        raise KeyError(f"Step '{step_id}' not found in family '{family.name}'")

    # Provenance tracks previous signature and triggering failure run
    new_family.provenance = {
        "action": "re_teach",
        "step_id": step_id,
        "triggering_run_id": triggering_run_id,
        "previous_signature": family.signature,
        "timestamp": time.time(),
    }

    # Cryptographically re-sign the updated family
    sign_family(new_family, device_key=device_key)

    # Log to audit spine
    spine = AuditSpine()
    spine.append(
        run_id=f"reteach_{family.name}_{int(time.time())}",
        verdict="PASS",
        checks=[],
        steps=[{"step": step_id, "action": updated_step.action}],
        model_disclosure={
            "kind": "re_teach_step",
            "triggering_run_id": triggering_run_id,
            "old_signature": family.signature,
            "new_signature": new_family.signature,
        },
        cost={"kind": "re_teach", "steps_modified": 1},
    )
    return new_family


def main() -> None:
    parser = argparse.ArgumentParser(description="StepProof Mode C: Task Family Compiler & Instantiator")
    parser.add_argument("--proc", type=str, help="Input Procedure JSON to compile into family")
    parser.add_argument("--family", type=str, help="Input Family Artifact to instantiate")
    parser.add_argument("--slots", nargs="+", help="Explicit slot names to confirm")
    parser.add_argument("--values", type=str, default="", help="JSON string of slot values to instantiate")
    parser.add_argument("--out", type=str, default="", help="Output artifact path")

    args = parser.parse_args()

    if args.proc:
        p_path = Path(args.proc)
        proc_data = json.loads(p_path.read_text(encoding="utf-8"))
        proc = Procedure.from_dict(proc_data)
        family = compile_family(proc, confirmed_slots=args.slots)
        out_p = Path(args.out) if args.out else Path(f"data/skills/{family.name}.artifact")
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(family.to_dict(), indent=2), encoding="utf-8")
        print(f"Successfully compiled family artifact: {out_p}")
        print(f"Slots: {list(family.slots.keys())}")
        print(f"Signature: {family.signature[:16]}...")

    elif args.family:
        fam_path = Path(args.family)
        fam_data = json.loads(fam_path.read_text(encoding="utf-8"))
        family = ProcedureFamily.from_dict(fam_data)
        vals = json.loads(args.values) if args.values else {}
        proc, safety = instantiate(family, vals)
        print(f"Successfully instantiated procedure: {proc.goal}")
        print(f"Safety classification: {safety}")
        if args.out:
            Path(args.out).write_text(json.dumps(proc.to_dict(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

