"""Render an Analysis as human-readable text or JSON."""

from __future__ import annotations

import json

from .analyze import Analysis, CoreConflict, Suggestion, suggest
from .versions import consensus_text


def _conflict_block(conflict: CoreConflict) -> list[str]:
    lines = [f"CONFLICT: no version of '{conflict.target}' satisfies "
             f"everything below", ""]
    blocker_ids = {id(b) for b in conflict.blockers}
    for c in conflict.constraints:
        marker = "  <-- BLOCKER" if id(c) in blocker_ids else ""
        req = "You requested" if c.user_requested else c.requirer_summary
        lines.append(f"  {req:<42} {conflict.target}{c.spec}{marker}")
    lines.append("")
    lines.append("  Why:")
    if len(conflict.blockers) == 1:
        b = conflict.blockers[0]
        rest = [c for c in conflict.constraints if c is not b]
        rest_range = consensus_text([s for c in rest for s in c.specs])
        who = "your pin" if b.user_requested else b.requirers[0].split()[0]
        lines.append(
            f"    {who} requires {conflict.target}{b.spec}, which does not "
            f"overlap {conflict.target} {rest_range} required by the "
            f"other {len(rest)} requirement(s).")
    else:
        lines.append(
            f"    {len(conflict.constraints)} requirements on "
            f"{conflict.target} have no common version"
            + ("; removing any single marked blocker would resolve it."
               if conflict.blockers else "."))
    lines.append("")
    lines.append("  Try:")
    for i, s in enumerate(suggest(conflict), 1):
        lines.append(f"    {i}. {s.text}")
        if s.detail:
            lines.append(f"       {s.detail}")
    return lines


def _requested_lines(requested: list[str]) -> list[str]:
    """Compress '-r requirements.txt (line N)' runs into a short summary."""
    import re
    files: dict[str, list[int]] = {}
    other: list[str] = []
    for r in requested:
        m = re.fullmatch(r"-r (\S+) \(line (\d+)\)", r.strip())
        if m:
            files.setdefault(m.group(1), []).append(int(m.group(2)))
        else:
            other.append(r)
    lines = []
    for fname, nums in files.items():
        nums = sorted(set(nums))
        # collapse runs: 2,7,8,10,12,13,14,15 -> "2, 7-8, 10, 12-15"
        runs, start, prev = [], nums[0], nums[0]
        for n in nums[1:]:
            if n == prev + 1:
                prev = n
            else:
                runs.append(str(start) if start == prev else f"{start}-{prev}")
                start = prev = n
        runs.append(str(start) if start == prev else f"{start}-{prev}")
        lines.append(f"-r {fname} (lines {', '.join(runs)})")
    lines.extend(other)
    return lines


def render_text(analysis: Analysis) -> str:
    lines = ["pipwhy: pip's dependency conflict, explained", ""]
    if analysis.report.requested:
        lines.append("You asked pip to install:")
        for r in _requested_lines(analysis.report.requested):
            lines.append(f"  - {r}")
        lines.append("")
    for conflict in analysis.conflicts:
        lines.extend(_conflict_block(conflict))
        lines.append("")
    for ic in analysis.installed:
        who = ic.requirer + (f" {ic.requirer_version}"
                             if ic.requirer_version else "")
        lines.append(
            f"INSTALLED CONFLICT: {who} requires "
            f"{ic.target}{ic.spec}, but you have {ic.target} "
            f"{ic.installed_version} installed.")
        lines.append(
            f"  Try: pip install \"{ic.target}{ic.spec}\" to match "
            f"{ic.requirer}'s requirement, or upgrade {ic.requirer} to a "
            f"release that supports {ic.target} {ic.installed_version}.")
        lines.append("")
    if not analysis.conflicts and not analysis.installed:
        lines.append("No conflicting core found in this output.")
        lines.append("If pip failed, paste more of the error (including the "
                     "\"The conflict is caused by:\" section).")
    return "\n".join(lines).rstrip() + "\n"


def render_json(analysis: Analysis) -> str:
    def constraint_dict(c):
        return {
            "target": c.target,
            "spec": c.spec,
            "requirers": c.requirers,
            "user_requested": c.user_requested,
        }

    payload = {
        "requested": analysis.report.requested,
        "conflicts": [
            {
                "target": cf.target,
                "constraints": [constraint_dict(c)
                                for c in cf.constraints],
                "blockers": [constraint_dict(c) for c in cf.blockers],
                "suggestions": [
                    {"text": s.text, "detail": s.detail}
                    for s in suggest(cf)
                ],
            }
            for cf in analysis.conflicts
        ],
        "installed_conflicts": [
            {
                "requirer": ic.requirer,
                "requirer_version": ic.requirer_version,
                "target": ic.target,
                "spec": ic.spec,
                "installed_version": ic.installed_version,
            }
            for ic in analysis.installed
        ],
    }
    return json.dumps(payload, indent=2) + "\n"
