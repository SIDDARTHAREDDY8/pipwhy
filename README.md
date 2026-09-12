# pipwhy

**pip's dependency conflicts, explained.** Pipe pip's `ResolutionImpossible`
error in, get the actual blocker out — instead of reading the resolver's raw
backtracking dump.

```bash
pip install -r requirements.txt 2>&1 | pipwhy
```

```text
pipwhy: pip's dependency conflict, explained

CONFLICT: no version of 'langchain-core' satisfies everything below

  You requested                              langchain-core==0.2.36
  langchain-anthropic 0.1.0                  langchain-core<0.2,>=0.1  <-- BLOCKER
  langchain 0.2.11, langchain-community 0.2.10 langchain-core<0.3.0,>=0.2.23
  langchain-openai 0.1.17                    langchain-core<0.3.0,>=0.2.20
  ...

  Why:
    langchain-anthropic requires langchain-core<0.2,>=0.1, which does not
    overlap langchain-core ==0.2.36 required by the other 6 requirement(s).

  Try:
    1. Upgrade langchain-anthropic — it looks like the blocker.
    2. Or pin langchain-core into langchain-anthropic's range ...
```

## Install

```bash
pip install git+https://github.com/SIDDARTHAREDDY8/pipwhy.git
```

Zero dependencies. Python 3.9+.

## Usage

```bash
# most common: pipe pip's stderr straight in
pip install -r requirements.txt 2>&1 | pipwhy

# or from a saved log
pip install . 2> pip-error.log; pipwhy pip-error.log

# machine-readable output for tooling
pip install -r requirements.txt 2>&1 | pipwhy --json
```

pipwhy understands both of pip's conflict reports:

- `ResolutionImpossible` — "Cannot install X because these package versions
  have conflicting dependencies" (the backtracking dump)
- the post-install report — "pip's dependency resolver does not currently
  take into account all the packages that are installed … but you have
  numpy 1.22.2 which is incompatible"

## What it does

1. **Parses** pip's error into structured requirements
   (`who requires what, which versions`).
2. **Collapses backtracking noise** — pip prints one line per version it
   tried, so `scipy 1.11.2/1.11.3/1.11.4` each repeating the same constraint
   becomes a single line.
3. **Finds the blocker** — the one requirement whose removal would make
   everything else satisfiable, using a small built-in PEP 440 version
   engine (no `packaging` dependency).
4. **Suggests fixes**, ranked: upgrade the blocker, loosen your pin, or
   confirm with an incremental install.

## Limitations

- pipwhy explains the conflict from pip's output alone — it never hits the
  network, so it can't tell you *which* newer version of the blocker fixes
  things, only that the blocker is the odd one out.
- Environment markers (`; python_version > "3.9"`) are stripped, not
  evaluated.
- Version comparison covers the PEP 440 constructs pip prints; exotic
  local versions (`1.0+abc.5`) compare approximately.

## License

MIT — see [LICENSE](LICENSE).
