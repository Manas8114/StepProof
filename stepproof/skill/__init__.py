"""Mode C: Operator skill compiler and parameterised task families.
Models perceive, code decides: parameterised slots, per-value safety classification,
cryptographic signing, and human-gated re-teaching.
"""
from .compile_family import (
    ProcedureFamily,
    compile_family,
    instantiate,
    propose_slots,
    re_teach_step,
)
from .from_demo import from_demo_file, from_describe

__all__ = [
    "ProcedureFamily",
    "compile_family",
    "instantiate",
    "propose_slots",
    "re_teach_step",
    "from_demo_file",
    "from_describe",
]

