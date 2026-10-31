from __future__ import annotations
from .muse import MuseSpark
from .sam_api import SamApi


def get_providers():
    return SamApi(), MuseSpark()
