"""Tests for the PEP 440 subset engine."""

import pytest

from pipwhy.versions import (
    cmp_versions,
    parse_specifier_set,
    satisfiable,
)


@pytest.mark.parametrize("a,b,expected", [
    ("1.0", "2.0", -1),
    ("2.0", "1.0", 1),
    ("1.0", "1.0", 0),
    ("1.10", "1.9", 1),
    ("1.0a1", "1.0", -1),
    ("1.0rc1", "1.0b2", 1),
    ("0.2.36", "0.2.4", 1),
    ("1.4.1", "1.4.1", 0),
    ("2.7.1", "2.7.1", 0),
])
def test_cmp_versions(a, b, expected):
    assert cmp_versions(a, b) == expected


@pytest.mark.parametrize("specs,expected", [
    ("<0.2,>=0.1", True),
    ("<0.3.0,>=0.2.23", True),
    ("==1.4.1", True),
    ("<1.4,>=1.3", True),
    ("<0.2,>=0.1,<0.3.0,>=0.2.23", False),   # disjoint ranges
    ("==1.4.1,<1.4,>=1.3", False),            # pin outside range
    ("==1.4.0,==1.4.1", False),               # two different pins
    ("==1.4.*", True),
    ("!=1.4.1", True),
    ("==1.4.1,!=1.4.1", False),
    (">=2", True),
    ("~=1.4.2", True),                        # >=1.4.2,<1.5
    ("~=1.4.2,<1.4.2", False),
    ("~=1.4.2,>=1.5", False),
    ("<1.28.0,>=1.21.6,>=2", False),          # scipy vs numpy>=2
    ("<1.29.0,>=1.22.4,>=2", False),
    ("<0.3,>=0.2.33", True),
    (">1.0,<1.0", False),                     # empty open interval
    (">1.0,<=1.0", False),
    (">=1.0,<=1.0", True),                    # single point, allowed
    (">=1.0,<=1.0,!=1.0", False),             # single point excluded
])
def test_satisfiable(specs, expected):
    assert satisfiable(parse_specifier_set(specs)) is expected


def test_parse_specifier_set_skips_junk():
    specs = parse_specifier_set(">=1.2, bogus !!")
    assert [s.op for s in specs] == [">="]
