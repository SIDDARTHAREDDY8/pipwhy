"""Minimal PEP 440 version / specifier engine (stdlib only).

pipwhy needs to answer one question about a set of version specifiers:
"is there any version that satisfies all of them?"  This module implements
just enough of PEP 440 to answer that exactly for the constraint language
pip prints (``==``, ``!=``, ``>=``, ``<=``, ``>``, ``<``, ``~=``, ``===``,
comma-separated conjunctions, ``.*`` wildcards).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

_PRE_ORDER = {"a": 0, "alpha": 0, "dev": 0, "b": 1, "beta": 1, "rc": 2,
              "c": 2, "preview": 2}
# Note: "post" is deliberately absent -> order 3, i.e. sorts after final.


def _split_version(text: str):
    """Split a version string into comparable segments.

    Returns a tuple of segments where each segment is ``(kind, value)`` with
    kind 0 = numeric, 1 = pre-release tag, 2 = other string.  Numeric segments
    compare numerically, everything else lexicographically, numerics sort
    before strings (matches the common cases of PEP 440).
    """
    text = text.strip().lower().lstrip("v")
    # separate pre/post/dev markers: 1.2rc1, 1.2a3, 1.0.post1, 1.0.dev4
    parts = re.split(r"[.\-_]", text)
    segments = []
    for part in parts:
        if not part:
            continue
        m = re.match(r"^(\d+)([a-zA-Z]+)(\d*)$", part)
        if m:
            num, tag, tagnum = m.groups()
            segments.append((0, int(num)))
            segments.append((1, (_PRE_ORDER.get(tag, 3), tag,
                                 int(tagnum) if tagnum else 0)))
            continue
        if part.isdigit():
            segments.append((0, int(part)))
        else:
            m2 = re.match(r"^([a-zA-Z]+)(\d*)$", part)
            if m2:
                tag, tagnum = m2.groups()
                segments.append((1, (_PRE_ORDER.get(tag, 3), tag,
                                     int(tagnum) if tagnum else 0)))
            else:
                segments.append((2, part))
    return tuple(segments)


def _seg_cmp(x, y):
    """Compare two segments (kind, value); kind 0=numeric, 1=tag, 2=string.

    A tag segment (1.0a1) is a pre/post-release *of* the numeric prefix, so
    numeric beats pre-release tags (1.0.1 > 1.0a1) and loses to post tags.
    """
    if x[0] != y[0]:
        kinds = {x[0], y[0]}
        if kinds == {0, 1}:
            tag = x if x[0] == 1 else y
            order = tag[1][0] if isinstance(tag[1], tuple) else 3
            numeric_wins = order <= 2  # pre/dev tags lose to the release
            if x[0] == 0:
                return 1 if numeric_wins else -1
            return -1 if numeric_wins else 1
        return -1 if x[0] < y[0] else 1
    xv, yv = x[1], y[1]
    if xv == yv:
        return 0
    return -1 if xv < yv else 1


def _missing_vs(seg):
    """Compare a missing (padded) segment against an existing one.

    A missing segment means "final release at this position": it sorts
    *after* pre-release/dev tags (1.0 > 1.0a1) but *before* post-release
    tags (1.0 < 1.0.post1), and equals numeric zero.
    Returns +1 if missing > seg, -1 if missing < seg, 0 if equal.
    """
    kind, val = seg
    if kind == 0:
        if val == 0:
            return 0
        return -1 if val > 0 else 1
    if kind == 1:
        order = val[0] if isinstance(val, tuple) else 3
        # _PRE_ORDER: a/b/rc/preview/dev -> 0..2 (pre), post -> 3
        return 1 if order <= 2 else -1
    return -1  # trailing string segment beats nothing


def cmp_versions(a: str, b: str) -> int:
    """Three-way compare of two version strings."""
    sa, sb = _split_version(a), _split_version(b)
    for i in range(max(len(sa), len(sb))):
        x = sa[i] if i < len(sa) else None
        y = sb[i] if i < len(sb) else None
        if x is None and y is None:
            continue
        if x is None:
            return _missing_vs(y)
        if y is None:
            return -_missing_vs(x)
        c = _seg_cmp(x, y)
        if c:
            return c
    return 0


# ---------------------------------------------------------------------------
# Specifiers
# ---------------------------------------------------------------------------

_SPEC_RE = re.compile(r"^(===|==|~=|!=|>=|<=|>|<)\s*(.+?)\s*$")


@dataclass
class Specifier:
    op: str
    version: str

    def satisfied_by(self, candidate: str) -> bool:
        if self.op == "===" or self.op == "==":
            if self.version.endswith(".*"):
                prefix = self.version[:-2].rstrip(".")
                c = candidate.strip().lower().lstrip("v")
                return c == prefix or c.startswith(prefix + ".")
            return cmp_versions(candidate, self.version) == 0
        if self.op == "!=":
            if self.version.endswith(".*"):
                prefix = self.version[:-2].rstrip(".")
                c = candidate.strip().lower().lstrip("v")
                return not (c == prefix or c.startswith(prefix + "."))
            return cmp_versions(candidate, self.version) != 0
        c = cmp_versions(candidate, self.version)
        if self.op == ">=":
            return c >= 0
        if self.op == "<=":
            return c <= 0
        if self.op == ">":
            return c > 0
        if self.op == "<":
            return c < 0
        if self.op == "~=":
            # PEP 440: ~= V.N means >= V.N, == V.* (prefix of all but last)
            lo_ok = cmp_versions(candidate, self.version) >= 0
            rel = self.version.split(".")
            if len(rel) < 2 or not rel[-2].isdigit():
                return False
            ub_parts = rel[:-1]
            ub_parts[-1] = str(int(ub_parts[-1]) + 1)
            ub = ".".join(ub_parts)
            return lo_ok and cmp_versions(candidate, ub) < 0
        return False


def parse_specifier_set(text: str) -> list[Specifier]:
    """Parse ``>=1.2,<2.0`` into [Specifier, ...]. Unknown junk is skipped."""
    specs = []
    for chunk in text.split(","):
        chunk = chunk.strip().rstrip(";").strip()
        if not chunk:
            continue
        m = _SPEC_RE.match(chunk)
        if m:
            specs.append(Specifier(m.group(1), m.group(2)))
    return specs


@dataclass
class Interval:
    """Feasibility interval for one package's allowed versions."""
    lower: str | None = None       # version string or None
    lower_inclusive: bool = True
    upper: str | None = None
    upper_inclusive: bool = True
    pins: list[str] = field(default_factory=list)   # == pins (non-wildcard)
    pin_prefixes: list[str] = field(default_factory=list)  # == X.* prefixes
    excludes: list[str] = field(default_factory=list)  # != pins


def _tighten_lower(iv: Interval, version: str, inclusive: bool):
    if iv.lower is None:
        iv.lower, iv.lower_inclusive = version, inclusive
        return
    c = cmp_versions(version, iv.lower)
    if c > 0 or (c == 0 and not inclusive and iv.lower_inclusive):
        iv.lower, iv.lower_inclusive = version, inclusive


def _tighten_upper(iv: Interval, version: str, inclusive: bool):
    if iv.upper is None:
        iv.upper, iv.upper_inclusive = version, inclusive
        return
    c = cmp_versions(version, iv.upper)
    if c < 0 or (c == 0 and not inclusive and iv.upper_inclusive):
        iv.upper, iv.upper_inclusive = version, inclusive


def _spec_to_interval(specs: list[Specifier]) -> Interval:
    iv = Interval()
    for s in specs:
        v = s.version
        if s.op in ("===", "=="):
            if v.endswith(".*"):
                iv.pin_prefixes.append(v[:-2].rstrip(".").lower())
            else:
                iv.pins.append(v)
        elif s.op == "!=":
            if v.endswith(".*"):
                # != X.* excludes a whole prefix: model as upper/lower cut is
                # complex; keep as exclusion checked against candidate points.
                iv.excludes.append(v)
            else:
                iv.excludes.append(v)
        elif s.op == ">=":
            _tighten_lower(iv, v, True)
        elif s.op == ">":
            _tighten_lower(iv, v, False)
        elif s.op == "<=":
            _tighten_upper(iv, v, True)
        elif s.op == "<":
            _tighten_upper(iv, v, False)
        elif s.op == "~=":
            _tighten_lower(iv, v, True)
            rel = v.split(".")
            if len(rel) >= 2 and rel[-2].isdigit():
                ub_parts = rel[:-1]
                ub_parts[-1] = str(int(ub_parts[-1]) + 1)
                _tighten_upper(iv, ".".join(ub_parts), False)
    return iv


def _point_excluded(point: str, iv: Interval) -> bool:
    for e in iv.excludes:
        if e.endswith(".*"):
            prefix = e[:-2].rstrip(".").lower()
            c = point.strip().lower().lstrip("v")
            if c == prefix or c.startswith(prefix + "."):
                return True
        elif cmp_versions(point, e) == 0:
            return True
    for p in iv.pin_prefixes:
        c = point.strip().lower().lstrip("v")
        if not (c == p or c.startswith(p + ".")):
            return True
    return False


def _in_interval(point: str, iv: Interval) -> bool:
    if iv.lower is not None:
        c = cmp_versions(point, iv.lower)
        if c < 0 or (c == 0 and not iv.lower_inclusive):
            return False
    if iv.upper is not None:
        c = cmp_versions(point, iv.upper)
        if c > 0 or (c == 0 and not iv.upper_inclusive):
            return False
    return True


def _bump(version: str) -> str:
    parts = version.split(".")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].isdigit():
            parts[i] = str(int(parts[i]) + 1)
            return ".".join(parts)
    return version + ".1"


def satisfiable(specs: list[Specifier]) -> bool:
    """True if at least one version can satisfy every specifier."""
    iv = _spec_to_interval(specs)
    # Pins must agree with each other and the interval.
    for p in iv.pins:
        if not _in_interval(p, iv) or _point_excluded(p, iv):
            return False
    uniq_pins = {p.lower() for p in iv.pins}
    if len(uniq_pins) > 1:
        return False
    if uniq_pins:
        return True  # the single pin survived interval + exclusions
    # Interval feasibility: lower <= upper (respecting inclusivity).
    if iv.lower is not None and iv.upper is not None:
        c = cmp_versions(iv.lower, iv.upper)
        if c > 0:
            return False
        if c == 0 and not (iv.lower_inclusive and iv.upper_inclusive):
            return False
        if c == 0:
            # Single-point interval: exclusions could kill it.
            return not _point_excluded(iv.lower, iv)
    # Candidate probe points: bounds, just-above-lower, and one version
    # inside each ==X.* prefix (a bare wildcard has no bounds at all).
    candidates = []
    if iv.lower is not None:
        candidates.append(iv.lower)
        candidates.append(_bump(iv.lower))
    if iv.upper is not None:
        candidates.append(iv.upper)
    for prefix in iv.pin_prefixes:
        candidates.append(prefix + ".0")
    candidates.append("9999.0")  # probe the unbounded-above case
    for cand in candidates:
        if _in_interval(cand, iv) and not _point_excluded(cand, iv):
            return True
    return False


def spec_text(specs: list[Specifier]) -> str:
    return ",".join(f"{s.op}{s.version}" for s in specs)


def consensus_text(specs: list[Specifier]) -> str:
    """Render the effective allowed range, e.g. ``>=0.2.36, <0.3``.

    Collapses a conjunction of specifiers into its tightest lower/upper
    bounds so reports read like a human summary instead of pip's dump.
    """
    iv = _spec_to_interval(specs)
    bits = []
    if iv.pins:
        uniq = sorted(set(iv.pins), key=str.lower)
        if len(uniq) == 1:
            return "==" + uniq[0]  # the pin is the effective range
        return " or ".join("==" + p for p in uniq)
    for prefix in iv.pin_prefixes:
        bits.append("==" + prefix + ".*")
    if iv.lower is not None:
        bits.append((">=" if iv.lower_inclusive else ">") + iv.lower)
    if iv.upper is not None:
        bits.append(("<=" if iv.upper_inclusive else "<") + iv.upper)
    for e in iv.excludes:
        bits.append("!=" + e)
    return ", ".join(bits) if bits else "any version"
