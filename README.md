# Cerebrum

LLM-based mutation testing, portable to any codebase.

Cerebrum inserts small, realistic bugs ("mutations") into a codebase one at a
time, runs the project's test suite, and reports whether the tests **caught**
each mutation. Mutations that survive reveal gaps in the test suite — each one
is a concrete bug that would ship silently.

The name is a nod to Cerebro, the machine in X-Men used to find mutants.

## Why another mutation tester?

Traditional mutation testers (Stryker, PIT, mutmut, cosmic-ray) rely on a
per-language AST library with a fixed set of operators (`+`→`-`, `<`→`<=`, …).
Cerebrum uses an **LLM as the mutation operator**, which:

- works on any language without a per-language mutator, and
- produces *domain-realistic* bugs that resemble real developer mistakes,
  stressing the test suite more meaningfully than mechanical operators.

## Core design: Engine + Adapter

- **The Engine is language-agnostic.** It knows git, patches, running a
  command, and comparing exit codes — never `npm`, `jest`, or `pytest`.
- **Everything codebase-specific lives in one `cerebrum.yaml`** committed to the
  target repo. Porting Cerebrum to a new codebase = writing that one file.

```
        cerebrum.yaml (per target repo)
        modules · install · test · globs
                     │ read by
        ┌────────────▼─────────────────────────────────────────┐
        │                 CEREBRUM ENGINE                       │
        │  1. BASELINE   install → run suite → require green    │
        │  2. TARGETING  pick lines (coverage | changed | ...)  │
        │  3. GENERATE   LLM → ONE mutant patch + metadata      │
        │  4. EXECUTE    worktree: apply → build → test → class │
        │  5. REPORT     score · survivors · suggested tests    │
        │                · severity-weighted trend across runs  │
        └───────────────────────────────────────────────────────┘
```

### Key principles

- **One mutant at a time** in an isolated git worktree — enables correct
  attribution of a test failure to a specific mutation.
- **Pure-LLM operator** behind a validity gate: a mutant only counts if its
  patch applies, changes behavior, and builds/lints.
- **Coverage-guided targeting** — never mutate uncovered lines (they survive
  trivially and add noise).
- **One targeting vocabulary**: `cerebrum run` sweeps a module using the
  strategy named in config (`coverage` by default); `cerebrum run --diff
  <base>..<head>` mutates only lines changed in that range (PR gate). The CLI
  never invents its own strategy names — `--diff` only supplies the range a
  committed config can't.

### Post-run hook

`cerebrum.yaml` accepts an optional top-level `after_run: <command>` — a single shell
command the engine runs, in the repo root, once a run's `.cerebrum/` artifacts
(`history.sqlite`, `runs/<run_id>/mutants.jsonl`, `runs/<run_id>/coverage.json`) have been
written. Use it to push results somewhere (e.g. `after_run: cerebrum-cloud-push` after `pip
install cerebrum-cloud-push` — see [`integrations/cerebrum-cloud/`](integrations/cerebrum-cloud/README.md)
for the Cerebrum Cloud client) without teaching the engine anything about the destination.
It's best-effort: a failing `after_run` command logs a warning to stderr but never fails the
run or changes its exit code or reported mutation score.

## Setup

Install the engine from the repo root: `pip install -e ".[dev]"`.

Cerebrum needs `ANTHROPIC_API_KEY` set in the process environment for mutation
generation and severity scoring — it only ever reads
`os.environ["ANTHROPIC_API_KEY"]` and has no opinion on how that variable gets
there.

Avoid putting the raw key in a plaintext `.env` — copy `.env.example` to
`.env` and put a *secrets-manager reference* in it instead, e.g. for
1Password:

```
ANTHROPIC_API_KEY=op://<vault>/<item>/credential
```

Then run through that tool so it resolves the reference into the `cerebrum`
child process only, never onto disk:

```
op run --env-file=.env -- cerebrum run -c cerebrum.yaml --module backend
```

The same pattern works with Doppler, Vault, or any other secrets manager —
Cerebrum doesn't care which one, as long as the real value lands in the
process environment before it runs. Don't bake a specific secrets tool into
shared scripts or docs; each user or environment should be free to supply the
key however they manage secrets.

## Status

Early, but the core loop runs. The config adapter, baseline stage, and the
**single-mutant lifecycle** (`cerebrum mutate`) are implemented: it selects a
covered line, asks Claude to insert one bug, applies it in an isolated git
worktree, runs the suite, classifies the outcome, and appends a record to
`.cerebrum/mutants.jsonl`. Generating a real mutant needs `ANTHROPIC_API_KEY` (see Setup).
Targeting and sweeps (`cerebrum run`, `--diff`) are implemented: pick covered
lines via the config's strategy or a changed-lines diff range, then mutate
them in parallel across a pool of pre-installed, reused git worktrees
(`runtime.parallelism`) instead of one at a time. Reporting (`cerebrum report`)
is implemented: mutation score, a survivor report with LLM-suggested tests, and
a severity-weighted trend across runs. Still to come: `llm-risk` and `all`
strategies.

## Mutant outcomes

`mutation_score = KILLED / (KILLED + SURVIVED)`

| Status        | Meaning                                            |
|---------------|----------------------------------------------------|
| `KILLED`      | A test failed — the suite caught the mutation.     |
| `SURVIVED`    | All tests passed — a real test gap.                |
| `TIMEOUT`     | Tests hung (e.g. infinite loop); counts as killed. |
| `BUILD_ERROR` | Mutant didn't compile/lint — invalid, discarded.   |
| `NO_COVERAGE` | Line has no covering tests — excluded.             |

## Trend tracking across runs

Each `cerebrum run` is a "run" in the trend sense: its mutant records land under
`.cerebrum/runs/<run_id>/mutants.jsonl`, and a summary row (score, kill/survive
counts, the git commit at the time, the average severity of that run's
survivors, and the module's code-coverage percentage) is appended to
`.cerebrum/history.sqlite`. A per-file coverage rollup for the run — covered vs.
instrumented line counts, coverage fraction, and the count and worst severity of
survivors per file — is also written to `.cerebrum/runs/<run_id>/coverage.json`,
so coverage can be trended over time and low-coverage files ranked by risk. Every
mutant now carries a
Claude-estimated `severity` (`low`/`medium`/`high`/`critical`) alongside its
`mutation_type`, so a declining score isn't the only signal — you can also see
whether the *impact* of what's surviving is trending up or down over time, not
just the count. `cerebrum report --trend` prints the last N runs; `cerebrum
report --survivors` prints the current run's survivors (file:line, diff,
severity, how many consecutive runs it's persisted) with an LLM-suggested test
for each. `cerebrum mutate` (a one-off manual mutation) is not part of this —
it still writes to the legacy flat `.cerebrum/mutants.jsonl` with no run or
history entry. Target repos should add `.cerebrum/` to their own `.gitignore`.
