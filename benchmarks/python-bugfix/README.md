# Python Bugfix Benchmark

Five small Python modules, each with a planted bug and a pytest file that exposes it. The agent must fix the code without touching the tests.

| Task | Module | Bug |
|---|---|---|
| bug-001 | `pagination.py` | Off-by-one on 1-indexed pages; page 0 not rejected |
| bug-002 | `tags.py` | Mutable default argument; mutates the caller's list |
| bug-003 | `money.py` | Float rounding (`round(2.675, 2) == 2.67`) instead of round-half-up |
| bug-004 | `stats.py` | Wrong even-length median; sorts the input in place; `IndexError` on empty |
| bug-005 | `words.py` | Case- and punctuation-sensitive counting; unstable tie order |

Each task's files live in `tasks/<id>/`. Dataset fields: `id`, `description` (the prompt), `image`, `module`, `test_file`.

## Usage

```bash
python setup.py bug-001 /path/to/workspace      # copies the module + tests
python evaluate.py bug-001 /path/to/workspace   # prints a JSON verdict, always exits 0
```

## Scoring

- **Score:** the fraction of the task's tests that pass (e.g. 4/5 = 0.8). Skipped tests count as not passed.
- **Pass:** only when every test passes.
- **Test file edited or deleted:** scores 0 and fails.
- **Tests running longer than 60s:** score 0.

Grading runs pytest with the grader's own Python, on the host.
