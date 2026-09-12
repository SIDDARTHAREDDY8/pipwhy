"""Parse pip's dependency-conflict error output into structured data.

Handles the two formats pip emits:

1. ``ResolutionImpossible`` (pip >= 20.3)::

       ERROR: Cannot install -r requirements.txt (line 2) and foo because
       these package versions have conflicting dependencies.

       The conflict is caused by:
           foo 1.0 depends on bar<2,>=1
           The user requested bar==3.0

2. The post-install "resolver does not take into account" report::

       ERROR: pip's dependency resolver does not currently take into account
       all the packages that are installed. This behaviour is the source of
       the following dependency conflicts.
           numba 0.55.1 requires numpy<1.22,>=1.18, but you have numpy 1.22.2
           which is incompatible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Requirement:
    """One 'X depends on Y<spec>' fact from pip's output."""
    requirer: str          # e.g. "langchain-anthropic" or "The user"
    requirer_version: str  # e.g. "0.1.0" or ""
    target: str            # e.g. "langchain-core"
    spec: str              # e.g. "<0.2,>=0.1"
    raw: str = ""          # original line, for display

    @property
    def requirer_label(self) -> str:
        v = f" {self.requirer_version}" if self.requirer_version else ""
        return f"{self.requirer}{v}"


@dataclass
class InstalledConflict:
    """One 'X requires Y<spec>, but you have Y Z' fact (variant 2)."""
    requirer: str
    requirer_version: str
    target: str
    spec: str
    installed_version: str
    raw: str = ""


@dataclass
class ConflictReport:
    requested: list[str] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    installed_conflicts: list[InstalledConflict] = field(default_factory=list)
    variant: str = ""  # "resolution-impossible" | "installed-conflicts" | ""


# "    foo 1.0 depends on bar<2,>=1" / "    The user requested bar==3.0"
_DEPENDS_RE = re.compile(
    r"^\s{2,}(?P<requirer>[A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)"
    r"(?:\s+(?P<version>[A-Za-z0-9_.\-+!*]+))?"
    r"\s+depends on\s+"
    r"(?P<target>[A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)"
    r"(?P<spec>[^;]*?)\s*$"
)
_USER_RE = re.compile(
    r"^\s{2,}The user requested\s+"
    r"(?P<target>[A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)"
    r"(?P<spec>.*?)\s*$"
)
# "    numba 0.55.1 requires numpy<1.22,>=1.18, but you have numpy 1.22.2 ..."
_INSTALLED_RE = re.compile(
    r"^\s{2,}(?P<requirer>[A-Za-z0-9_.\-]+)"
    r"(?:\s+(?P<rversion>[A-Za-z0-9_.\-+!*]+))?"
    r"\s+requires\s+"
    r"(?P<target>[A-Za-z0-9_.\-]+)"
    r"(?P<spec>[^,]*?(?:,[^,]*?)*?)"   # the spec, up to ", but you have"
    r",\s*but you have\s+"
    r"[A-Za-z0-9_.\-]+\s+(?P<iversion>[A-Za-z0-9_.\-+!*]+)"
)

_HEADER_RE = re.compile(
    r"^ERROR: Cannot install (?P<reqs>.+?) because these package versions "
    r"have conflicting dependencies\.\s*$"
)
_VARIANT2_RE = re.compile(
    r"dependency conflicts\.\s*$"
)


def _clean_spec(spec: str) -> str:
    # strip environment markers ("; python_version > ...") and quotes;
    # pip sometimes prints "X and >=Y" instead of "X,>=Y".
    spec = spec.split(";")[0].strip().strip("\"'")
    spec = re.sub(r"\s+and\s+", ",", spec)
    return spec


def _split_header_reqs(reqs: str) -> list[str]:
    """Split pip's 'Cannot install A, B and C' list on ", " / " and ".

    Bracket-aware: extras like ``pkg[extra1,extra2]==1.0`` contain commas
    that must not split.
    """
    parts, depth, buf = [], 0, ""
    i = 0
    tokens: list[str] = []
    while i < len(reqs):
        ch = reqs[i]
        if ch == "[":
            depth += 1
            buf += ch
            i += 1
        elif ch == "]":
            depth = max(0, depth - 1)
            buf += ch
            i += 1
        elif depth == 0 and reqs.startswith(", ", i):
            tokens.append(buf)
            buf = ""
            i += 2
        elif depth == 0 and reqs.startswith(" and ", i):
            tokens.append(buf)
            buf = ""
            i += 5
        else:
            buf += ch
            i += 1
    tokens.append(buf)
    return [t.strip() for t in tokens if t.strip()]
    # strip environment markers ("; python_version > ...") and quotes;
    # pip sometimes prints "X and >=Y" instead of "X,>=Y".
    spec = spec.split(";")[0].strip().strip("\"'")
    spec = re.sub(r"\s+and\s+", ",", spec)
    return spec


def parse(text: str) -> ConflictReport:
    report = ConflictReport()
    # Variant 2 lines can wrap mid-sentence at terminal width, e.g.
    # "... but you have numpy 1.22.2 which is\n    incompatible." — join an
    # indented line onto the previous one when the previous line looks like
    # an unfinished conflict report.
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        prev = lines[-1] if lines else ""
        looks_unfinished = bool(prev) and re.search(
            r"\b(requires|depends on)\b", prev) and \
            "incompatible" not in prev and "conflict" not in prev.lower()
        looks_continuation = bool(re.match(r"^\s{2,}\S", raw)) and \
            not re.search(r"\b(depends on|requires|requested)\b", stripped) \
            and not stripped.startswith("ERROR")
        if looks_unfinished and looks_continuation:
            lines[-1] = prev.rstrip() + " " + stripped
        else:
            lines.append(raw)

    in_caused_by = False
    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            report.variant = "resolution-impossible"
            # pip joins the request list with ", " and " and ".
            report.requested = _split_header_reqs(m.group("reqs"))
            in_caused_by = False
            continue
        if "The conflict is caused by:" in line:
            in_caused_by = True
            continue
        if "To fix this you could try to:" in line:
            in_caused_by = False
            continue
        if _VARIANT2_RE.search(line):
            report.variant = report.variant or "installed-conflicts"
            in_caused_by = True
            continue

        if not in_caused_by:
            continue

        mu = _USER_RE.match(line)
        if mu:
            report.requirements.append(Requirement(
                requirer="The user", requirer_version="",
                target=mu.group("target"),
                spec=_clean_spec(mu.group("spec") or ""),
                raw=line.strip()))
            continue

        mi = _INSTALLED_RE.match(line)
        if mi:
            report.installed_conflicts.append(InstalledConflict(
                requirer=mi.group("requirer"),
                requirer_version=mi.group("rversion") or "",
                target=mi.group("target"),
                spec=_clean_spec(mi.group("spec") or ""),
                installed_version=mi.group("iversion"),
                raw=line.strip()))
            continue

        md = _DEPENDS_RE.match(line)
        if md:
            report.requirements.append(Requirement(
                requirer=md.group("requirer"),
                requirer_version=md.group("version") or "",
                target=md.group("target"),
                spec=_clean_spec(md.group("spec") or ""),
                raw=line.strip()))
            continue

    return report


def found_conflict(report: ConflictReport) -> bool:
    return bool(report.requirements or report.installed_conflicts)
