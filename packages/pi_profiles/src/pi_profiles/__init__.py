"""Vertical profiles (ADR-0007 §4, ADR-0008 §3): per-vertical attribute models and size rules."""

from pi_profiles.base import Attr, AttributeModel, VerticalProfile
from pi_profiles.beauty import BEAUTY_V1, BEAUTY_V2, BeautyAttributesV1, BeautyAttributesV2
from pi_profiles.registry import PROFILES, REF_PATTERN, UnknownProfileError, get_profile

__all__ = [
    "BEAUTY_V1",
    "BEAUTY_V2",
    "PROFILES",
    "REF_PATTERN",
    "Attr",
    "AttributeModel",
    "BeautyAttributesV1",
    "BeautyAttributesV2",
    "UnknownProfileError",
    "VerticalProfile",
    "get_profile",
]
