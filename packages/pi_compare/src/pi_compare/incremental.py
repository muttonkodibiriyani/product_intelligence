"""Append-only comparison generations and narrowly scoped cache invalidation.

The projection builder remains pure.  This module records accepted outputs, proves that the
caller's listing change set covers every changed family, and names only the family/facet cache
keys whose inputs changed.  Replaying an input identity is a no-op with a byte check; rollback
moves the served pointer without deleting a manifest or event.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import quote

from pydantic import Field, StringConstraints, model_validator

from pi_compare.models import ComparisonProjection, ProductFamily, Sha256
from pi_core.types import NonEmptyStr, UtcDatetime
from pi_dataset.models import ContractModel

GenerationKey = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class EventKind(StrEnum):
    BUILD = "build"
    CORRECTION = "correction"
    ROLLBACK = "rollback"


class BuildIdentity(ContractModel):
    """Every immutable input that can affect a comparison generation."""

    source_generation: GenerationKey
    match_generation: GenerationKey
    attribute_profile_version: GenerationKey
    description_generation: GenerationKey
    builder_version: GenerationKey

    @property
    def idempotency_key(self) -> str:
        return _sha(self.model_dump(mode="json", by_alias=True))


class FamilyIndexEntry(ContractModel):
    fingerprint: Sha256
    listing_keys: tuple[NonEmptyStr, ...]
    cache_keys: tuple[NonEmptyStr, ...]


class ProjectionManifest(ContractModel):
    schema_id: Literal["pi.comparison-manifest/v1"] = Field(
        default="pi.comparison-manifest/v1", alias="schema"
    )
    generation: GenerationKey
    identity: BuildIdentity
    idempotency_key: Sha256
    projection_sha256: Sha256
    families: dict[NonEmptyStr, FamilyIndexEntry]
    previous_generation: GenerationKey | None = None

    @model_validator(mode="after")
    def _check_identity(self) -> Self:
        if self.idempotency_key != self.identity.idempotency_key:
            msg = "manifest idempotency key does not match its build identity"
            raise ValueError(msg)
        return self


class IncrementalChangeSet(ContractModel):
    changed_listing_keys: tuple[NonEmptyStr, ...]
    old_family_ids: tuple[NonEmptyStr, ...]
    new_family_ids: tuple[NonEmptyStr, ...]
    affected_family_ids: tuple[NonEmptyStr, ...]
    invalidated_cache_keys: tuple[NonEmptyStr, ...]
    member_visits: int = Field(ge=0)


class ProjectionEvent(ContractModel):
    event_id: Sha256
    sequence: int = Field(gt=0)
    kind: EventKind
    generation: GenerationKey
    from_generation: GenerationKey | None
    idempotency_key: Sha256
    changes: IncrementalChangeSet
    actor: NonEmptyStr
    reason: NonEmptyStr
    recorded_at: UtcDatetime
    supersedes_event_id: Sha256 | None = None

    @model_validator(mode="after")
    def _check_event_id(self) -> Self:
        expected = _sha(
            _event_values(
                sequence=self.sequence,
                kind=self.kind,
                generation=self.generation,
                from_generation=self.from_generation,
                idempotency_key=self.idempotency_key,
                changes=self.changes,
                actor=self.actor,
                reason=self.reason,
                recorded_at=self.recorded_at,
                supersedes_event_id=self.supersedes_event_id,
            )
        )
        if self.event_id != expected:
            raise ValueError("event id does not match its immutable audit fields")
        return self


class ProjectionHistory(ContractModel):
    schema_id: Literal["pi.comparison-history/v1"] = Field(
        default="pi.comparison-history/v1", alias="schema"
    )
    manifests: tuple[ProjectionManifest, ...] = ()
    events: tuple[ProjectionEvent, ...] = ()
    served_generation: GenerationKey | None = None

    @model_validator(mode="after")
    def _check_append_only_chain(self) -> Self:
        generations = _validate_manifests(self.manifests)
        _validate_events(self.events, generations)
        if self.served_generation is not None and self.served_generation not in generations:
            raise ValueError("served generation has no append-only manifest")
        if self.manifests and self.served_generation is None:
            raise ValueError("non-empty history needs a served generation")
        return self


def _validate_manifests(manifests: tuple[ProjectionManifest, ...]) -> set[str]:
    generations = [item.generation for item in manifests]
    identities = [item.idempotency_key for item in manifests]
    if len(generations) != len(set(generations)):
        raise ValueError("history repeats a generation")
    if len(identities) != len(set(identities)):
        raise ValueError("history repeats an idempotency key")
    prior_generations: set[str] = set()
    for manifest in manifests:
        if manifest.previous_generation is None and prior_generations:
            raise ValueError("a later manifest has no previous generation")
        if (
            manifest.previous_generation is not None
            and manifest.previous_generation not in prior_generations
        ):
            raise ValueError("manifest previous generation is absent or later")
        prior_generations.add(manifest.generation)
    return prior_generations


def _validate_events(events: tuple[ProjectionEvent, ...], generations: set[str]) -> None:
    if [event.sequence for event in events] != list(range(1, len(events) + 1)):
        raise ValueError("history event sequences are not contiguous")
    event_ids = [event.event_id for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("history repeats an event id")
    known_events: set[str] = set()
    for event in events:
        if event.generation not in generations:
            raise ValueError("event generation has no append-only manifest")
        if event.from_generation is not None and event.from_generation not in generations:
            raise ValueError("event source generation has no append-only manifest")
        if (
            event.supersedes_event_id is not None
            and event.supersedes_event_id not in known_events
        ):
            raise ValueError("an event supersedes an absent or later event")
        known_events.add(event.event_id)


@dataclass(frozen=True, slots=True)
class ApplyResult:
    history: ProjectionHistory
    changes: IncrementalChangeSet
    replayed: bool


def empty_history() -> ProjectionHistory:
    return ProjectionHistory()


def build_manifest(
    projection: ComparisonProjection,
    identity: BuildIdentity,
    *,
    previous_generation: str | None = None,
) -> ProjectionManifest:
    """Create the deterministic manifest persisted before the served pointer advances."""
    return ProjectionManifest(
        generation=projection.generation,
        identity=identity,
        idempotency_key=identity.idempotency_key,
        projection_sha256=_sha(projection.model_dump(mode="json", by_alias=True)),
        families={family.id: _index_family(family) for family in projection.families},
        previous_generation=previous_generation,
    )


def apply_projection(  # noqa: PLR0913 - an atomic transition has explicit audit inputs
    history: ProjectionHistory,
    *,
    previous: ComparisonProjection | None,
    current: ComparisonProjection,
    identity: BuildIdentity,
    changed_listing_keys: tuple[str, ...],
    actor: str,
    reason: str,
    recorded_at: UtcDatetime,
    supersedes_event_id: str | None = None,
) -> ApplyResult:
    """Append one accepted generation, or return the unchanged history for an exact replay."""
    manifest = build_manifest(
        current,
        identity,
        previous_generation=None if previous is None else previous.generation,
    )
    replay = next(
        (item for item in history.manifests if item.idempotency_key == manifest.idempotency_key),
        None,
    )
    if replay is not None:
        if replay.projection_sha256 != manifest.projection_sha256:
            raise ValueError("idempotency key replay produced different projection bytes")
        return ApplyResult(history=history, changes=_empty_changes(), replayed=True)

    _validate_transition(history, previous, current, manifest)
    prior = None if previous is None else _manifest(history, previous.generation)
    changes = _changes(prior, manifest, changed_listing_keys)
    kind = EventKind.CORRECTION if supersedes_event_id is not None else EventKind.BUILD
    if supersedes_event_id is not None and not any(
        event.event_id == supersedes_event_id for event in history.events
    ):
        raise ValueError("correction supersedes an unknown event")
    event = _event(
        sequence=len(history.events) + 1,
        kind=kind,
        generation=current.generation,
        from_generation=None if previous is None else previous.generation,
        idempotency_key=manifest.idempotency_key,
        changes=changes,
        actor=actor,
        reason=reason,
        recorded_at=recorded_at,
        supersedes_event_id=supersedes_event_id,
    )
    updated = ProjectionHistory(
        manifests=(*history.manifests, manifest),
        events=(*history.events, event),
        served_generation=current.generation,
    )
    return ApplyResult(history=updated, changes=changes, replayed=False)


def rollback(
    history: ProjectionHistory,
    *,
    target_generation: str,
    actor: str,
    reason: str,
    recorded_at: UtcDatetime,
) -> ApplyResult:
    """Move the served pointer to an earlier manifest and retain every record."""
    target = _manifest(history, target_generation)
    if history.served_generation == target_generation:
        return ApplyResult(history=history, changes=_empty_changes(), replayed=True)
    if history.served_generation is None:
        raise ValueError("cannot roll back an empty history")
    current = _manifest(history, history.served_generation)
    affected = tuple(
        sorted(
            family_id
            for family_id in set(current.families) | set(target.families)
            if current.families.get(family_id) != target.families.get(family_id)
        )
    )
    changes = IncrementalChangeSet(
        changed_listing_keys=(),
        old_family_ids=tuple(fid for fid in affected if fid in current.families),
        new_family_ids=tuple(fid for fid in affected if fid in target.families),
        affected_family_ids=affected,
        invalidated_cache_keys=_cache_keys(current, target, affected),
        member_visits=sum(
            len(manifest.families[fid].listing_keys)
            for manifest in (current, target)
            for fid in affected
            if fid in manifest.families
        ),
    )
    event = _event(
        sequence=len(history.events) + 1,
        kind=EventKind.ROLLBACK,
        generation=target_generation,
        from_generation=current.generation,
        idempotency_key=target.idempotency_key,
        changes=changes,
        actor=actor,
        reason=reason,
        recorded_at=recorded_at,
        supersedes_event_id=None,
    )
    updated = ProjectionHistory(
        manifests=history.manifests,
        events=(*history.events, event),
        served_generation=target_generation,
    )
    return ApplyResult(history=updated, changes=changes, replayed=False)


def _validate_transition(
    history: ProjectionHistory,
    previous: ComparisonProjection | None,
    current: ComparisonProjection,
    manifest: ProjectionManifest,
) -> None:
    if any(item.generation == current.generation for item in history.manifests):
        raise ValueError(f"generation already exists: {current.generation}")
    if previous is None:
        if history.manifests:
            raise ValueError("non-empty history requires the currently served projection")
        return
    if previous.generation != history.served_generation:
        raise ValueError("previous projection is not the served generation")
    served = _manifest(history, previous.generation)
    if served.projection_sha256 != _sha(previous.model_dump(mode="json", by_alias=True)):
        raise ValueError("previous projection bytes do not match its persisted manifest")
    if manifest.generation == previous.generation:
        raise ValueError("a new projection needs a new generation")


def _changes(
    previous: ProjectionManifest | None,
    current: ProjectionManifest,
    changed_listing_keys: tuple[str, ...],
) -> IncrementalChangeSet:
    changed = tuple(sorted(set(changed_listing_keys)))
    if not changed:
        raise ValueError("an accepted build needs at least one changed listing key")
    changed_set = set(changed)
    old_ids = () if previous is None else _families_for(previous, changed_set)
    new_ids = _families_for(current, changed_set)
    affected = tuple(sorted(set(old_ids) | set(new_ids)))
    if not affected:
        raise ValueError("changed listing keys do not resolve to an old or new family")
    if previous is None and set(affected) != set(current.families):
        raise ValueError("initial build change set does not cover every family")
    if previous is not None:
        unexpected = tuple(
            sorted(
                family_id
                for family_id in set(previous.families) | set(current.families)
                if family_id not in affected
                and previous.families.get(family_id) != current.families.get(family_id)
            )
        )
        if unexpected:
            raise ValueError(f"family changes are missing listing keys: {unexpected}")
    return IncrementalChangeSet(
        changed_listing_keys=changed,
        old_family_ids=old_ids,
        new_family_ids=new_ids,
        affected_family_ids=affected,
        invalidated_cache_keys=_cache_keys(previous, current, affected),
        member_visits=sum(
            len(manifest.families[fid].listing_keys)
            for manifest in (previous, current)
            if manifest is not None
            for fid in affected
            if fid in manifest.families
        ),
    )


def _families_for(manifest: ProjectionManifest, listing_keys: set[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            family_id
            for family_id, entry in manifest.families.items()
            if listing_keys.intersection(entry.listing_keys)
        )
    )


def _index_family(family: ProductFamily) -> FamilyIndexEntry:
    listing_keys = tuple(sorted(f"{item.retailer}:{item.token}" for item in family.listings))
    payload = family.model_dump(mode="json", by_alias=True)
    for cell in payload["matrix"]:
        cell.pop("generation", None)
    return FamilyIndexEntry(
        fingerprint=_sha(payload),
        listing_keys=listing_keys,
        cache_keys=_family_cache_keys(family),
    )


def _family_cache_keys(family: ProductFamily) -> tuple[str, ...]:
    keys = {f"family:{_part(family.id)}", f"facet:brand:{_part(family.brand_key)}"}
    keys.add(f"facet:category:{_part('/'.join(family.category))}")
    for cell in family.matrix:
        keys.add(f"facet:matrix:{_part(cell.retailer)}:{cell.state.value}")
    for listing in family.listings:
        keys.add(f"facet:retailer:{_part(listing.retailer)}")
        keys.add(f"facet:price:{_part(listing.retailer)}")
        keys.add(f"facet:discount:{_part(listing.retailer)}")
        keys.add(f"facet:offer:{_part(listing.retailer)}")
        keys.add(f"facet:launch:{_part(listing.retailer)}")
        keys.add(f"facet:attribute-completeness:{_part(listing.retailer)}")
        for commercial in listing.commercial:
            keys.add(
                f"facet:availability:{_part(listing.retailer)}:"
                f"{commercial.availability_state.value}"
            )
            for money in (commercial.current, commercial.regular):
                if money is not None:
                    keys.add(f"facet:currency:{money.currency}")
        for variant in listing.variants:
            for axis in variant.axes:
                if axis.canonical is not None:
                    keys.add(
                        f"facet:{axis.axis.value}:"
                        f"{_part(json.dumps(axis.canonical, sort_keys=True))}"
                    )
    return tuple(sorted(keys))


def _cache_keys(
    previous: ProjectionManifest | None,
    current: ProjectionManifest,
    affected: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                key
                for manifest in (previous, current)
                if manifest is not None
                for family_id in affected
                if family_id in manifest.families
                for key in manifest.families[family_id].cache_keys
            }
        )
    )


def _event(  # noqa: PLR0913 - exact persisted audit fields
    *,
    sequence: int,
    kind: EventKind,
    generation: str,
    from_generation: str | None,
    idempotency_key: str,
    changes: IncrementalChangeSet,
    actor: str,
    reason: str,
    recorded_at: UtcDatetime,
    supersedes_event_id: str | None,
) -> ProjectionEvent:
    values = _event_values(
        sequence=sequence,
        kind=kind,
        generation=generation,
        from_generation=from_generation,
        idempotency_key=idempotency_key,
        changes=changes,
        actor=actor,
        reason=reason,
        recorded_at=recorded_at,
        supersedes_event_id=supersedes_event_id,
    )
    return ProjectionEvent(
        event_id=_sha(values),
        sequence=sequence,
        kind=kind,
        generation=generation,
        from_generation=from_generation,
        idempotency_key=idempotency_key,
        changes=changes,
        actor=actor,
        reason=reason,
        recorded_at=recorded_at,
        supersedes_event_id=supersedes_event_id,
    )


def _event_values(  # noqa: PLR0913 - exact persisted audit fields
    *,
    sequence: int,
    kind: EventKind,
    generation: str,
    from_generation: str | None,
    idempotency_key: str,
    changes: IncrementalChangeSet,
    actor: str,
    reason: str,
    recorded_at: UtcDatetime,
    supersedes_event_id: str | None,
) -> dict[str, object]:
    return {
        "sequence": sequence,
        "kind": kind.value,
        "generation": generation,
        "fromGeneration": from_generation,
        "idempotencyKey": idempotency_key,
        "changes": changes.model_dump(mode="json", by_alias=True),
        "actor": actor,
        "reason": reason,
        "recordedAt": recorded_at.isoformat(),
        "supersedesEventId": supersedes_event_id,
    }


def _manifest(history: ProjectionHistory, generation: str) -> ProjectionManifest:
    found = next((item for item in history.manifests if item.generation == generation), None)
    if found is None:
        raise ValueError(f"unknown comparison generation: {generation}")
    return found


def _empty_changes() -> IncrementalChangeSet:
    return IncrementalChangeSet(
        changed_listing_keys=(),
        old_family_ids=(),
        new_family_ids=(),
        affected_family_ids=(),
        invalidated_cache_keys=(),
        member_visits=0,
    )


def _sha(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _part(value: str) -> str:
    return quote(value, safe="")
