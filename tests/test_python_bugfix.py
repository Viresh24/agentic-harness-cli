"""Checks the python-bugfix benchmark itself: every bug is real, every fix is gradable, test edits are caught."""

import pytest

from agentic_harness.benchmarks import load_benchmark
from agentic_harness.models import TaskStatus

FIXES = {
    "bug-001": (
        "pagination.py",
        "def paginate(items, page, per_page):\n"
        "    if page < 1:\n"
        "        raise ValueError('pages start at 1')\n"
        "    start = (page - 1) * per_page\n"
        "    return items[start : start + per_page]\n",
    ),
    "bug-002": (
        "tags.py",
        "def add_tag(tag, tags=None):\n"
        "    tags = list(tags or [])\n"
        "    if tag not in tags:\n"
        "        tags.append(tag)\n"
        "    return tags\n",
    ),
    "bug-003": (
        "money.py",
        "from decimal import ROUND_HALF_UP, Decimal\n\n\n"
        "def round_price(amount):\n"
        "    return float(Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))\n",
    ),
    "bug-004": (
        "stats.py",
        "def median(values):\n"
        "    if not values:\n"
        "        raise ValueError('empty')\n"
        "    ordered = sorted(values)\n"
        "    mid = len(ordered) // 2\n"
        "    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2\n",
    ),
    "bug-005": (
        "words.py",
        "import re\nfrom collections import Counter\n\n\n"
        "def top_words(text, n):\n"
        "    counts = Counter(re.findall(r'[a-z0-9]+', text.lower()))\n"
        "    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]\n",
    ),
}


@pytest.fixture(scope="module")
def bench():
    return load_benchmark("python-bugfix")


def _setup(bench, task_id, tmp_path):
    task = bench.get_tasks([task_id])[0]
    workspace = tmp_path / "ws"
    bench.setup(task, workspace, tmp_path / "logs")
    return task, workspace


def test_dataset_matches_fixes(bench):
    assert sorted(t.id for t in bench.list_tasks()) == sorted(FIXES)


def test_prompt_names_files_and_forbids_editing_tests(bench):
    prompt = bench.render_prompt(bench.get_tasks(["bug-001"])[0])
    assert "pagination.py" in prompt and "test_pagination.py" in prompt and "not the tests" in prompt


@pytest.mark.parametrize(("task_id",), [(t,) for t in FIXES])
def test_planted_bug_fails_some_tests(bench, task_id, tmp_path):
    task, workspace = _setup(bench, task_id, tmp_path)
    outcome = bench.evaluate(task, workspace, tmp_path / "logs")
    assert outcome.status == TaskStatus.FAILED
    assert 0 <= outcome.score < 1
    assert outcome.details["details"]["tests_passed"] < outcome.details["details"]["tests_total"]


@pytest.mark.parametrize(("task_id",), [(t,) for t in FIXES])
def test_reference_fix_scores_full_marks(bench, task_id, tmp_path):
    task, workspace = _setup(bench, task_id, tmp_path)
    filename, code = FIXES[task_id]
    (workspace / filename).write_text(code)
    outcome = bench.evaluate(task, workspace, tmp_path / "logs")
    assert (outcome.status, outcome.score) == (TaskStatus.PASSED, 1.0)


def test_editing_the_tests_scores_zero(bench, tmp_path):
    task, workspace = _setup(bench, "bug-001", tmp_path)
    (workspace / "test_pagination.py").write_text("def test_nothing():\n    assert True\n")
    outcome = bench.evaluate(task, workspace, tmp_path / "logs")
    assert (outcome.status, outcome.score) == (TaskStatus.FAILED, 0.0)
    assert outcome.details["details"]["test_file_modified"] is True


def test_partial_fix_gets_partial_credit(bench, tmp_path):
    task, workspace = _setup(bench, "bug-004", tmp_path)
    # Fixes the empty-list and mutation bugs but still returns the upper middle for even lengths.
    (workspace / "stats.py").write_text(
        "def median(values):\n"
        "    if not values:\n"
        "        raise ValueError('empty')\n"
        "    ordered = sorted(values)\n"
        "    return ordered[len(ordered) // 2]\n"
    )
    outcome = bench.evaluate(task, workspace, tmp_path / "logs")
    assert outcome.status == TaskStatus.FAILED and outcome.score == 0.8
