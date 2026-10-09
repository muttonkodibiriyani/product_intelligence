"""Evidence-backed cross-retailer comparison primitives."""

from pi_compare.attributes import validate_attribute, validate_attributes
from pi_compare.models import (
    AttributeCell,
    AttributeObservation,
    AttributeReport,
    AttributeSpec,
    Axis,
    AxisValue,
    CaptureCompleteness,
    ComparisonProjection,
    Discount,
    DiscountResult,
    EvidencePointer,
    ImageDescription,
    ImageDescriptionFile,
    MatrixState,
    ProductFamily,
    RetailerCell,
    ValueState,
)
from pi_compare.normalise import discount, normalise_size, normalise_text_axis
from pi_compare.presence import retailer_cell
from pi_compare.projection import build_projection

__all__ = [
    "AttributeCell",
    "AttributeObservation",
    "AttributeReport",
    "AttributeSpec",
    "Axis",
    "AxisValue",
    "CaptureCompleteness",
    "ComparisonProjection",
    "Discount",
    "DiscountResult",
    "EvidencePointer",
    "ImageDescription",
    "ImageDescriptionFile",
    "MatrixState",
    "ProductFamily",
    "RetailerCell",
    "ValueState",
    "build_projection",
    "discount",
    "normalise_size",
    "normalise_text_axis",
    "retailer_cell",
    "validate_attribute",
    "validate_attributes",
]
