"""Conflict analysis: minimal cores, blockers, and fix suggestions.

Given pip's parsed "X depends on Y<spec>" facts, pipwhy groups constraints by
target package, collapses pip's backtracking noise (the same constraint
repeated for every version pip tried), then finds the *minimal conflicting
core* — the smallest set of requirements that cannot all be satisfied — and
names the *blocker*: the constraint whose removal would resolve the conflict.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field

from .parse import ConflictReport, InstalledConflict, Requirement
from .versions import (Specifier, cmp_versions, consensus_text,
                       parse_specifier_set, satisfiable)


@dataclass
class Constraint:
    target: str
    spec: str
    specs: list[Specifier]
    requirers: list[str]          # e.g. ["scipy 1.11.2", "scipy 1.11.3"]
    user_requested: bool = False

    @property
    def requirer_summary(self) -> str:
        names = [r.split()[0] for r in self.requirers]
        uniq = list(dict.fromkeys(names))
        if len(uniq) == 1 and len(self.requirers) > 1:
            versions = [r.split()[1] for r in self.requirers if " " in r]
            if versions:
                ordered = sorted(set(versions),
                                 key=functools.cmp_to_key(cmp_versions))
                return f"{uniq[0]} {ordered[0]}–{ordered[-1]} " \
                       f"({len(self.requirers)} tried versions)"
            return f"{uniq[0]} (x{len(self.requirers)})"
        return ", ".join(self.requirers)


@dataclass
class CoreConflict:
    target: str
    constraints: list[Constraint]  # every distinct constraint on the target
    blockers: list[Constraint]      # removing any one of these resolves it


@dataclass
class Analysis:
    report: ConflictReport
    conflicts: list[CoreConflict] = field(default_factory=list)
    installed: list[InstalledConflict] = field(default_factory=list)


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-").split("[")[0]


def group_constraints(reqs: list[Requirement]) -> dict[str, list[Constraint]]:
    """Group requirements by target, collapsing backtracking noise.

    pip prints one line per (tried version, dependency) pair, so the same
    logical constraint appears many times (e.g. scipy 1.11.2/1.11.3/1.11.4
    each "depends on numpy<1.28,>=1.21.6").  Collapse those into one
    Constraint with all the tried versions recorded.
    """
    buckets: dict[tuple[str, str, bool], Constraint] = {}
    for r in reqs:
        key = (_normalize(r.target), r.spec.strip(),
               r.requirer == "The user")
        c = buckets.get(key)
        label = r.requirer_label
        if c is None:
            buckets[key] = Constraint(
                target=_normalize(r.target), spec=r.spec.strip(),
                specs=parse_specifier_set(r.spec),
                requirers=[label],
                user_requested=(r.requirer == "The user"))
        elif label not in c.requirers:
            c.requirers.append(label)
    grouped: dict[str, list[Constraint]] = {}
    for c in buckets.values():
        grouped.setdefault(c.target, []).append(c)
    return grouped


def _all_specs(constraints: list[Constraint]) -> list[Specifier]:
    out: list[Specifier] = []
    for c in constraints:
        out.extend(c.specs)
    return out


def find_blockers(constraints: list[Constraint]) -> list[Constraint]:
    """Constraints whose individual removal makes the set satisfiable.

    pip's output lists every version it tried, so the same logical
    constraint appears repeatedly; those were already collapsed by
    group_constraints().  What remains is the real disagreement, and the
    blocker is the odd one out — the requirement the other N agree against.
    """
    blockers = []
    for c in constraints:
        rest = [x for x in constraints if x is not c]
        if rest and satisfiable(_all_specs(rest)):
            blockers.append(c)
    return blockers


def analyze(report: ConflictReport) -> Analysis:
    analysis = Analysis(report=report, installed=report.installed_conflicts)
    grouped = group_constraints(report.requirements)
    for target, constraints in grouped.items():
        with_specs = [c for c in constraints if c.specs]
        if len(with_specs) < 2:
            continue
        if satisfiable(_all_specs(with_specs)):
            continue
        analysis.conflicts.append(CoreConflict(
            target=target, constraints=with_specs,
            blockers=find_blockers(with_specs)))
    # Deterministic order: most constrained target first.
    analysis.conflicts.sort(key=lambda c: (-len(c.constraints), c.target))
    return analysis


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

@dataclass
class Suggestion:
    text: str
    detail: str = ""


def suggest(conflict: CoreConflict) -> list[Suggestion]:
    """Ranked, concrete fix suggestions for one core conflict."""
    out: list[Suggestion] = []
    constraints = conflict.constraints
    blockers = conflict.blockers

    user_pins = [c for c in constraints if c.user_requested]
    pkg_blockers = [c for c in blockers if not c.user_requested]
    user_blockers = [c for c in blockers if c.user_requested]

    if len(pkg_blockers) == 1 and not user_blockers:
        b = pkg_blockers[0]
        rest = [c for c in constraints if c is not b]
        rest_range = consensus_text([s for c in rest for s in c.specs])
        out.append(Suggestion(
            f"Upgrade {b.requirers[0].split()[0]} — it looks like the blocker.",
            f"{b.requirer_summary} requires {conflict.target}{b.spec}, while "
            f"{len(rest)} other requirement(s) agree on "
            f"{conflict.target} {rest_range}. A newer release of "
            f"{b.requirers[0].split()[0]} probably supports that range; "
            f"check its changelog."))
        out.append(Suggestion(
            f"Or pin {conflict.target} into {b.requirers[0].split()[0]}'s "
            f"range ({conflict.target}{b.spec}) and see what breaks.",
            "This satisfies the blocker but will likely conflict with the "
            "other packages — use it to confirm the diagnosis, then prefer "
            "the upgrade path above."))
    elif pkg_blockers:
        names = ", ".join(sorted({b.requirers[0].split()[0]
                                  for b in pkg_blockers}))
        out.append(Suggestion(
            f"Several blockers ({names}) — no single package is at fault.",
            "Try upgrading all of them together; often a consistent newer "
            "set exists. If not, split the environment (two venvs / "
            "separate services)."))

    for up in user_blockers:
        out.append(Suggestion(
            f"Loosen your pin: you asked for {conflict.target}{up.spec}.",
            "Your explicit requirement is the blocker. Removing the pin "
            "(or widening it) lets pip pick a version the other packages "
            "agree on."))
    for up in user_pins:
        if up not in user_blockers:
            out.append(Suggestion(
                f"Note: you pinned {conflict.target}{up.spec}.",
                "Your pin participates in the conflict. If loosening it "
                "doesn't help, the disagreeing packages need upgrading."))

    if not out:
        out.append(Suggestion(
            "No single blocker — the requirements genuinely disagree.",
            "Look for a set of versions released around the same time, or "
            "isolate the disagreeing packages into separate environments."))

    out.append(Suggestion(
        "Sanity check: create a fresh venv and install incrementally.",
        "pip's error only shows the failing state; installing your "
        "requirements one at a time reveals exactly which addition "
        "breaks the resolve."))

    # De-duplicate while preserving order.
    seen, uniq = set(), []
    for s in out:
        if s.text not in seen:
            seen.add(s.text)
            uniq.append(s)
    return uniq
