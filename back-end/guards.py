"""Centralized guard registry for market phase transitions (D16).

Every precondition for every phase transition lives in this single file.
Each guard bundles its ``id``, ``description``, and ``evaluate()`` method.
Adding or removing a precondition edits ONLY this file -- the endpoint and
frontend never change.

Design: guards are plain Python classes, not a rules engine (D16 refined).
No ABC, no DSL, no runtime mutation. Read this file to understand every
precondition in the system.

Phase 1 guards implemented:
  - ``FormHasFieldsGuard``  on every edge into ``applications_open``
    (``draft -> applications_open`` and ``applications_closed -> applications_open``)

Skeleton guards for later phases are intentionally omitted.
They will be added with their phases (one-file edit, proven by this PR).
"""

from dataclasses import dataclass, field
from typing import Optional

from datatypes import Market


# ── Wire shape (backend/frontend contract) ──────────────────────────────


@dataclass
class PreconditionResult:
    """Evaluated outcome of a guard check. The frontend renders this generically.

    This is the load-bearing design decision (D16). The ``BlockerPanel``
    component receives a list of these objects and renders each one with
    zero guard-specific logic.
    """
    id: str
    passed: bool
    message: str
    resolution_link: Optional[str] = None


# ── Guard classes ───────────────────────────────────────────────────────


class FormHasFieldsGuard:
    """Application form must have at least one field before publishing."""

    id: str = "form_has_fields"
    description: str = "Application form has at least one field"

    def evaluate(self, market: Market, db) -> PreconditionResult:
        form = market.application_form
        if form is None or len(form.fields) == 0:
            return PreconditionResult(
                id=self.id,
                passed=False,
                message=(
                    "The application form has no fields. "
                    "Add at least one field before publishing the market."
                ),
                resolution_link=f"/markets/{market.id}/form-builder",
            )
        return PreconditionResult(id=self.id, passed=True, message="")


# ── Transition registry ─────────────────────────────────────────────────


# Phase 1 valid transitions. Transitions not in this set return 400
# ("transition not available in current phase").
# Adding a new phase transition: add to this set + add to TRANSITION_GUARDS
# if the transition has preconditions.
VALID_TRANSITIONS: set[tuple[str, str]] = {
    ("draft", "applications_open"),
    ("applications_open", "applications_closed"),
    ("applications_closed", "applications_open"),
}

# Guards are stateless, so one instance is shared by every edge that enforces it.
_FORM_HAS_FIELDS = FormHasFieldsGuard()

# (from_phase, to_phase) -> list of guard instances.
# Transitions in VALID_TRANSITIONS but absent here have no preconditions
# (admin authority -- the organiser decides when to advance).
# ADDING A GUARD = append to the list. REMOVING = delete from the list.
# No other file changes. Not the endpoint. Not the frontend.
#
# A precondition is a property of the TARGET phase, so it must be listed on
# EVERY edge into that phase. `applications_open` has two inbound edges and
# both carry FormHasFieldsGuard: a market cannot sit in applications_open with
# an empty form regardless of the route it took to get there.
TRANSITION_GUARDS: dict[tuple[str, str], list] = {
    ("draft", "applications_open"): [_FORM_HAS_FIELDS],
    ("applications_closed", "applications_open"): [_FORM_HAS_FIELDS],
}


# ── Registry self-check ─────────────────────────────────────────────────


def _validate_registry() -> None:
    """Fail at import if the two tables above disagree.

    ``VALID_TRANSITIONS`` and ``TRANSITION_GUARDS`` are hand-maintained, and both ways
    of getting them out of sync fail silently at runtime: ``evaluate_transition`` looks
    guards up by edge, so a guard listed on a non-existent edge never runs, and an edge
    that forgot a guard simply reports no blockers. Editing this file is only safe if the
    file catches both, so it checks them here rather than trusting a reviewer to.
    """
    unreachable = set(TRANSITION_GUARDS) - VALID_TRANSITIONS
    if unreachable:
        raise RuntimeError(
            "TRANSITION_GUARDS lists edges that are not in VALID_TRANSITIONS: "
            f"{sorted(unreachable)}. Guards on an edge that cannot be taken never run."
        )

    guard_ids_by_edge_into: dict[str, dict[str, frozenset]] = {}
    for from_phase, to_phase in VALID_TRANSITIONS:
        guards = TRANSITION_GUARDS.get((from_phase, to_phase), [])
        guard_ids_by_edge_into.setdefault(to_phase, {})[from_phase] = frozenset(
            guard.id for guard in guards
        )

    for to_phase, guard_ids_by_from in guard_ids_by_edge_into.items():
        if len(set(guard_ids_by_from.values())) > 1:
            detail = ", ".join(
                f"{from_phase} -> {to_phase}: {sorted(ids) or 'no guards'}"
                for from_phase, ids in sorted(guard_ids_by_from.items())
            )
            raise RuntimeError(
                f"Inbound edges into '{to_phase}' enforce different preconditions "
                f"({detail}). A precondition is a property of the target phase, so every "
                "edge into a phase must carry the same guards or the invariant is only "
                "enforced on the route the author happened to think about."
            )


_validate_registry()


# ── Evaluation helpers ──────────────────────────────────────────────────


def evaluate_transition(
    market: Market, to_phase: str, db
) -> list[PreconditionResult]:
    """Evaluate all guards for a transition. Returns only FAILED results.

    If the transition has no guards, returns an empty list (no blockers).
    Callers use this to build the 409 blocker list or confirm success.
    """
    key = (market.phase.value, to_phase)
    guards = TRANSITION_GUARDS.get(key, [])
    blockers: list[PreconditionResult] = []
    for guard in guards:
        result = guard.evaluate(market, db)
        if not result.passed:
            blockers.append(result)
    return blockers
