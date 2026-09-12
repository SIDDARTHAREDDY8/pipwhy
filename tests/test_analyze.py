"""End-to-end tests: parse real-world pip outputs, find the blocker."""

from pathlib import Path

import pytest

from pipwhy.analyze import analyze, group_constraints
from pipwhy.parse import found_conflict, parse

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text()


def test_langchain_core_blocker():
    report = parse(load("langchain-core.txt"))
    assert found_conflict(report)
    assert report.variant == "resolution-impossible"
    analysis = analyze(report)
    assert len(analysis.conflicts) == 1
    conflict = analysis.conflicts[0]
    assert conflict.target == "langchain-core"
    # The blocker is the single outlier: langchain-anthropic 0.1.0.
    assert len(conflict.blockers) == 1
    blocker = conflict.blockers[0]
    assert blocker.requirers[0].startswith("langchain-anthropic")
    assert blocker.spec == "<0.2,>=0.1"
    # All constraints stay visible: the user pin plus every package.
    # langchain + langchain-community share one spec, so they collapse.
    assert len(conflict.constraints) == 7
    assert any(c.user_requested for c in conflict.constraints)
    collapsed = [c for c in conflict.constraints
                 if len(c.requirers) == 2]
    assert len(collapsed) == 1
    assert "langchain-community" in collapsed[0].requirer_summary


def test_numpy_scipy_noise_collapsed():
    report = parse(load("numpy-scipy.txt"))
    analysis = analyze(report)
    assert len(analysis.conflicts) == 1
    conflict = analysis.conflicts[0]
    assert conflict.target == "numpy"
    # Backtracking noise: scipy 1.11.2/1.11.3/1.11.4 collapse into one
    # constraint; the user's numpy>=2 pin is the blocker.
    by_requirer = {c.requirer_summary: c for c in conflict.constraints}
    scipy_keys = [k for k in by_requirer if k.startswith("scipy 1.11")]
    assert len(scipy_keys) == 1, by_requirer.keys()
    assert "3 tried versions" in scipy_keys[0]
    assert len(conflict.blockers) == 1
    assert conflict.blockers[0].user_requested


def test_installed_conflict_variant():
    report = parse(load("installed-conflict.txt"))
    assert found_conflict(report)
    assert report.variant == "installed-conflicts"
    analysis = analyze(report)
    assert len(analysis.installed) == 2
    first = analysis.installed[0]
    assert (first.requirer, first.target, first.installed_version) == \
        ("numba", "numpy", "1.22.2")


def test_extras_conflict():
    report = parse(load("extras.txt"))
    analysis = analyze(report)
    assert len(analysis.conflicts) == 1
    conflict = analysis.conflicts[0]
    assert conflict.target == "pandas"
    assert len(conflict.constraints) == 2


def test_no_conflict_input():
    report = parse("Successfully installed foo-1.0 bar-2.0\n")
    assert not found_conflict(report)


def test_grouping_is_case_insensitive():
    report = parse(
        "ERROR: Cannot install a and b because these package versions have "
        "conflicting dependencies.\n"
        "\n"
        "The conflict is caused by:\n"
        "    Foo 1.0 depends on Bar<2,>=1\n"
        "    baz 2.0 depends on bar>=2\n"
    )
    grouped = group_constraints(report.requirements)
    assert set(grouped) == {"bar"}
    assert len(grouped["bar"]) == 2
