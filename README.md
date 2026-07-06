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
        └───────────────────────────────────────────────────────┘
```

### Key principles

- **One mutant at a time** in an isolated git worktree — enables correct
  attribution of a test failure to a specific mutation.
- **Pure-LLM operator** behind a validity gate: a mutant only counts if its
  patch applies, changes behavior, and builds/lints.
- **Coverage-guided targeting** — never mutate uncovered lines (they survive
  trivially and add noise).
- **Two run modes**: `--diff` (PR gate, changed lines) and `--full`
  (scheduled sweep, coverage-guided, score trend over time).

## Status

Early, but the core loop runs. The config adapter, baseline stage, and the
**single-mutant lifecycle** (`cerebrum mutate`) are implemented: it selects a
covered line, asks Claude to insert one bug, applies it in an isolated git
worktree, runs the suite, classifies the outcome, and appends a record to
`.cerebrum/mutants.jsonl`. Generating a real mutant needs `ANTHROPIC_API_KEY`.
Still to come: parallel worktree pool (#4), smart targeting and run modes (#5),
and reporting (#6).

## Mutant outcomes

`mutation_score = KILLED / (KILLED + SURVIVED)`

| Status        | Meaning                                            |
|---------------|----------------------------------------------------|
| `KILLED`      | A test failed — the suite caught the mutation.     |
| `SURVIVED`    | All tests passed — a real test gap.                |
| `TIMEOUT`     | Tests hung (e.g. infinite loop); counts as killed. |
| `BUILD_ERROR` | Mutant didn't compile/lint — invalid, discarded.   |
| `NO_COVERAGE` | Line has no covering tests — excluded.             |
