"""Benchmark loading: `--benchmark <name|path>` -> Benchmark."""

import importlib
import os
from pathlib import Path

import yaml

from agentic_harness.benchmarks.base import Benchmark, BenchmarkError, BenchmarkNotFoundError, UnknownTaskError
from agentic_harness.benchmarks.script import ScriptBenchmark

MANIFEST = "harness.yaml"

__all__ = [
    "Benchmark",
    "BenchmarkError",
    "BenchmarkNotFoundError",
    "ScriptBenchmark",
    "UnknownTaskError",
    "benchmarks_dir",
    "load_benchmark",
    "resolve_benchmark_dir",
]


def benchmarks_dir() -> Path:
    return Path(os.environ.get("HARNESS_BENCHMARKS_DIR", "benchmarks"))


def resolve_benchmark_dir(name_or_path: str) -> Path:
    """Absolute folder holding the benchmark's harness.yaml, given a path or a name under benchmarks_dir()."""
    for path in (Path(name_or_path), benchmarks_dir() / name_or_path):
        if (path / MANIFEST).is_file():
            return path.resolve()
    root = benchmarks_dir()
    available = sorted(p.parent.name for p in root.glob(f"*/{MANIFEST}")) if root.is_dir() else []
    raise BenchmarkNotFoundError(
        f"No benchmark {name_or_path!r} (looked for {MANIFEST} in {name_or_path!r} and {root / name_or_path}). "
        f"Available: {', '.join(available) or 'none'}"
    )


def load_benchmark(name_or_path: str) -> Benchmark:
    """Load a benchmark by name or path, using its manifest's `class:` if set, else ScriptBenchmark."""
    manifest_path = resolve_benchmark_dir(name_or_path) / MANIFEST
    cls_spec = yaml.safe_load(manifest_path.read_text()).get("class")
    cls = _import_class(cls_spec) if cls_spec else ScriptBenchmark
    return cls.from_manifest(manifest_path)


def _import_class(spec: str) -> type[Benchmark]:
    module_name, _, attr = spec.partition(":")
    cls = getattr(importlib.import_module(module_name), attr, None)
    if not (isinstance(cls, type) and issubclass(cls, Benchmark)):
        raise BenchmarkError(f"class {spec!r} is not a Benchmark subclass")
    return cls
