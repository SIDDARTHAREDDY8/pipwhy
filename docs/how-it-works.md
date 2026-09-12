# How pipwhy works

## Pipeline

```
pip's stderr -> parse -> group_constraints -> find_blockers -> suggest -> render
```

### 1. Parse (`parse.py`)

Two formats are recognized:

**ResolutionImpossible** (pip >= 20.3). The header line

```
ERROR: Cannot install -r requirements.txt (line 2) and foo because these
package versions have conflicting dependencies.
```

is split (bracket-aware, so `pkg[extra1,extra2]==1.0` survives) into the
requested list. Lines under `The conflict is caused by:` match one of:

- `    <name> <version> depends on <target><spec>[; marker]`
- `    The user requested <target><spec>`

**Installed-conflicts** ("pip's dependency resolver does not currently take
into account…"). Lines look like:

```
    numba 0.55.1 requires numpy<1.22,>=1.18, but you have numpy 1.22.2
    which is incompatible.
```

Wrapped lines are re-joined before matching. Environment markers are
stripped from specs; pip's occasional `X and >=Y` phrasing is normalized
to `X,>=Y`.

### 2. Group (`analyze.group_constraints`)

pip prints one line per (tried version × dependency) pair, so identical
logical constraints repeat. Requirements are bucketed by
`(normalized target, spec, user_requested)` and the tried versions are
kept for display (`scipy 1.11.2–1.11.4 (3 tried versions)`). Packages that
share a spec collapse too (`langchain 0.2.11, langchain-community 0.2.10`).

### 3. Blocker detection (`analyze.find_blockers`)

For each target whose constraints are jointly unsatisfiable, every
constraint is tested: if removing it (and only it) restores
satisfiability, it is a **blocker**. Usually there is exactly one — the
odd package out.

Satisfiability is decided by `versions.satisfiable`, a small stdlib-only
PEP 440 engine: each specifier set is reduced to an interval
(lower/upper bound + pins + exclusions) and checked for a feasible point.
Supported operators: `==` (incl. `.*`), `!=`, `>=`, `<=`, `>`, `<`, `~=`,
`===`.

### 4. Suggestions (`analyze.suggest`)

Ranked heuristics:

1. Single package blocker → "upgrade X; its newer releases probably
   support the consensus range" (+ the reverse pin as a diagnostic).
2. User pin is the blocker → "loosen your pin".
3. Multiple blockers → upgrade together or split environments.
4. Fallback → incremental install in a fresh venv.

### 5. Render (`report.py`)

Human text (default) or `--json` with `requested`, `conflicts`
(`target`, `constraints`, `blockers`, `suggestions`) and
`installed_conflicts`.
