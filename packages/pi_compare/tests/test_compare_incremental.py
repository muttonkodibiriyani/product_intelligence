"""Incremental comparison generation, replay, cache and rollback tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from pi_compare import (
    BuildIdentity,
    CaptureCompleteness,
    EventKind,
    ProjectionHistory,
    apply_projection,
    build_manifest,
    build_projection,
    empty_history,
    rollback,
)
from pi_compare.models import ComparisonProjection, ProductFamily
from pi_dataset import DatasetV3

FIXTURE = Path("packages/pi_api/tests/fixtures/v3-main-66bc083.json")
NOW = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)


def projection(generation: str = "g1") -> ComparisonProjection:
    dataset = DatasetV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    completeness = {
        "shop_a": CaptureCompleteness(complete=True, basis="saved_complete_capture"),
        "shop_b": CaptureCompleteness(complete=True, basis="saved_complete_capture"),
        "shop_c": CaptureCompleteness(complete=False, basis="source_partial"),
        "shop_d": CaptureCompleteness(complete=False, basis="source_blocked"),
    }
    return build_projection(dataset, generation=generation, completeness=completeness)


def identity(version: str = "source-1") -> BuildIdentity:
    return BuildIdentity(
        source_generation=version,
        match_generation="match-1",
        attribute_profile_version="attributes-1",
        description_generation="descriptions-1",
        builder_version="pi_compare.incremental/1",
    )


def listing_key(family: ProductFamily, index: int = 0) -> str:
    listing = family.listings[index]
    return f"{listing.retailer}:{listing.token}"


def all_listing_keys(body: ComparisonProjection) -> tuple[str, ...]:
    return tuple(
        listing_key(family, index)
        for family in body.families
        for index in range(len(family.listings))
    )


def next_projection(
    previous: ComparisonProjection,
    generation: str,
    changes: dict[str, dict[str, object]] | None = None,
) -> ComparisonProjection:
    changes = {} if changes is None else changes
    families = []
    for family in previous.families:
        matrix = tuple(cell.model_copy(update={"generation": generation}) for cell in family.matrix)
        values = {"matrix": matrix, **changes.get(family.id, {})}
        families.append(family.model_copy(update=values))
    return previous.model_copy(update={"generation": generation, "families": tuple(families)})


def initial_history() -> tuple[ProjectionHistory, ComparisonProjection]:
    body = projection()
    result = apply_projection(
        empty_history(),
        previous=None,
        current=body,
        identity=identity(),
        changed_listing_keys=all_listing_keys(body),
        actor="pipeline",
        reason="initial accepted generation",
        recorded_at=NOW,
    )
    return result.history, body


def test_manifest_and_initial_event_are_deterministic_and_append_only() -> None:
    body = projection()
    first = build_manifest(body, identity())
    again = build_manifest(body, identity())

    assert first.model_dump_json(by_alias=True) == again.model_dump_json(by_alias=True)
    assert first.idempotency_key == identity().idempotency_key

    history, _ = initial_history()
    assert history.served_generation == "g1"
    assert len(history.manifests) == len(history.events) == 1
    assert history.events[0].kind is EventKind.BUILD
    assert history.events[0].changes.affected_family_ids == tuple(sorted(first.families))


def test_initial_change_set_must_cover_every_family() -> None:
    body = projection()
    with pytest.raises(ValueError, match="does not cover every family"):
        apply_projection(
            empty_history(),
            previous=None,
            current=body,
            identity=identity(),
            changed_listing_keys=(listing_key(body.families[0]),),
            actor="pipeline",
            reason="incomplete initial build",
            recorded_at=NOW,
        )


def test_exact_replay_is_byte_identical_and_appends_nothing() -> None:
    history, body = initial_history()
    before = history.model_dump_json(by_alias=True)

    result = apply_projection(
        history,
        previous=body,
        current=body,
        identity=identity(),
        changed_listing_keys=(listing_key(body.families[0]),),
        actor="pipeline",
        reason="retry",
        recorded_at=NOW,
    )

    assert result.replayed
    assert result.changes.member_visits == 0
    assert result.history.model_dump_json(by_alias=True) == before


def test_one_listing_invalidates_only_its_old_and_new_family_buckets() -> None:
    history, old = initial_history()
    target = old.families[0]
    other = old.families[1]
    new = next_projection(old, "g2", {target.id: {"name": f"{target.name} corrected"}})

    result = apply_projection(
        history,
        previous=old,
        current=new,
        identity=identity("source-2"),
        changed_listing_keys=(listing_key(target), listing_key(target)),
        actor="pipeline",
        reason="accepted listing correction",
        recorded_at=NOW,
    )

    assert not result.replayed
    assert result.changes.changed_listing_keys == (listing_key(target),)
    assert result.changes.affected_family_ids == (target.id,)
    assert result.changes.member_visits == 2 * len(target.listings)
    assert f"family:{target.id}" in result.changes.invalidated_cache_keys
    assert f"family:{other.id}" not in result.changes.invalidated_cache_keys
    assert any(key.startswith("facet:price:") for key in result.changes.invalidated_cache_keys)
    assert any(key.startswith("facet:offer:") for key in result.changes.invalidated_cache_keys)
    assert any(key.startswith("facet:launch:") for key in result.changes.invalidated_cache_keys)
    assert result.history.served_generation == "g2"
    assert len(result.history.manifests) == len(result.history.events) == 2


def test_unreported_family_change_is_rejected_before_pointer_advance() -> None:
    history, old = initial_history()
    first, second = old.families[:2]
    new = next_projection(
        old,
        "g2",
        {first.id: {"name": "changed one"}, second.id: {"name": "changed two"}},
    )

    with pytest.raises(ValueError, match="family changes are missing listing keys"):
        apply_projection(
            history,
            previous=old,
            current=new,
            identity=identity("source-2"),
            changed_listing_keys=(listing_key(first),),
            actor="pipeline",
            reason="incomplete change set",
            recorded_at=NOW,
        )


def test_family_merge_visits_only_old_and_new_members() -> None:
    history, old = initial_history()
    first, second = old.families[:2]
    merged = first.model_copy(
        update={
            "id": "fam-merged-fixture",
            "name": "reviewed merged family",
            "listings": (*first.listings, *second.listings),
            "matrix": tuple(
                cell.model_copy(update={"generation": "g2"}) for cell in first.matrix
            ),
        }
    )
    untouched = tuple(
        family.model_copy(
            update={
                "matrix": tuple(
                    cell.model_copy(update={"generation": "g2"}) for cell in family.matrix
                )
            }
        )
        for family in old.families[2:]
    )
    new = old.model_copy(update={"generation": "g2", "families": (merged, *untouched)})

    result = apply_projection(
        history,
        previous=old,
        current=new,
        identity=identity("source-2"),
        changed_listing_keys=(listing_key(first), listing_key(second)),
        actor="matcher",
        reason="accepted family edge",
        recorded_at=NOW,
    )

    assert result.changes.old_family_ids == tuple(sorted((first.id, second.id)))
    assert result.changes.new_family_ids == (merged.id,)
    assert result.changes.affected_family_ids == tuple(
        sorted((first.id, second.id, merged.id))
    )
    old_members = len(first.listings) + len(second.listings)
    assert result.changes.member_visits == old_members + len(merged.listings)
    assert result.changes.member_visits == 2 * old_members


def test_same_idempotency_key_cannot_publish_different_bytes() -> None:
    history, old = initial_history()
    changed = next_projection(old, "g2", {old.families[0].id: {"name": "different"}})

    with pytest.raises(ValueError, match="replay produced different projection bytes"):
        apply_projection(
            history,
            previous=old,
            current=changed,
            identity=identity(),
            changed_listing_keys=(listing_key(old.families[0]),),
            actor="pipeline",
            reason="invalid retry",
            recorded_at=NOW,
        )


def test_correction_points_to_superseded_event() -> None:
    history, old = initial_history()
    target = old.families[0]
    new = next_projection(old, "g2", {target.id: {"name": "corrected"}})

    result = apply_projection(
        history,
        previous=old,
        current=new,
        identity=identity("source-2"),
        changed_listing_keys=(listing_key(target),),
        actor="reviewer",
        reason="reviewed correction",
        recorded_at=NOW,
        supersedes_event_id=history.events[0].event_id,
    )

    event = result.history.events[-1]
    assert event.kind is EventKind.CORRECTION
    assert event.supersedes_event_id == history.events[0].event_id
    assert result.history.manifests[-1].previous_generation == "g1"


def test_rollback_moves_pointer_and_never_deletes_history() -> None:
    history, old = initial_history()
    target = old.families[0]
    new = next_projection(old, "g2", {target.id: {"name": "changed"}})
    applied = apply_projection(
        history,
        previous=old,
        current=new,
        identity=identity("source-2"),
        changed_listing_keys=(listing_key(target),),
        actor="pipeline",
        reason="accepted update",
        recorded_at=NOW,
    )

    result = rollback(
        applied.history,
        target_generation="g1",
        actor="operator",
        reason="live verification failed",
        recorded_at=NOW,
    )

    assert result.history.served_generation == "g1"
    assert result.history.manifests == applied.history.manifests
    assert result.history.events[:-1] == applied.history.events
    assert result.history.events[-1].kind is EventKind.ROLLBACK
    assert result.changes.affected_family_ids == (target.id,)
    assert f"family:{target.id}" in result.changes.invalidated_cache_keys

    replay = rollback(
        result.history,
        target_generation="g1",
        actor="operator",
        reason="duplicate request",
        recorded_at=NOW,
    )
    assert replay.replayed
    assert replay.history == result.history


def test_history_rejects_event_tampering_and_unknown_rollback() -> None:
    history, _ = initial_history()
    bad = history.events[0].model_copy(update={"sequence": 2})
    with pytest.raises(ValidationError, match="event id does not match"):
        ProjectionHistory(
            manifests=history.manifests,
            events=(bad,),
            served_generation=history.served_generation,
        )
    tampered = history.events[0].model_copy(update={"reason": "changed after persistence"})
    with pytest.raises(ValidationError, match="event id does not match"):
        ProjectionHistory(
            manifests=history.manifests,
            events=(tampered,),
            served_generation=history.served_generation,
        )
    with pytest.raises(ValueError, match="unknown comparison generation"):
        rollback(
            history,
            target_generation="missing",
            actor="operator",
            reason="mistyped generation",
            recorded_at=NOW,
        )
