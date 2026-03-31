#!/usr/bin/env python3
"""
Evaluate pp-ocr proposed table extraction against saved/live competitors.

This script lives in autoresearch-mlx so the repo can act as an orchestration
surface for improving an external target repo (`pp-ocr`) on a fixed dataset.
It runs the target repo benchmark in its own virtualenv, compares the live
`proposed` lane against saved or live competitor baselines, and appends a TSV
row for autonomous experiment loops.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PP_OCR_ROOT = Path("/Users/mean/Documents/Github/pp-ocr")
DEFAULT_DATASET = DEFAULT_PP_OCR_ROOT / "data" / "benchmarks" / "hf_finance_legal_mrc"
DEFAULT_OUTPUT = REPO_ROOT / "pp_ocr_finance_legal_latest.json"
DEFAULT_RESULTS_TSV = REPO_ROOT / "pp_ocr_results.tsv"
DEFAULT_TARGET_FILE = REPO_ROOT / "pp_ocr_finance_legal_targets.json"
DEFAULT_PROPOSED_METHOD = "proposed"
COMPETITOR_METHODS = ("external_paddleocr_vl", "external_glm_ocr")
JSON_SENTINEL = "__PP_OCR_EVAL_JSON__"
MIN_SECRET_LENGTH = 32


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate pp-ocr proposed lane against hf_finance_legal_mrc competition targets."
    )
    parser.add_argument("--pp-ocr-root", type=Path, default=DEFAULT_PP_OCR_ROOT)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--pp-ocr-python", type=Path, default=None)
    parser.add_argument("--proposed-method", default=DEFAULT_PROPOSED_METHOD)
    parser.add_argument("--max-samples", type=int, default=10, help="0 means full dataset.")
    parser.add_argument("--sample-start", type=int, default=0)
    parser.add_argument("--run-live-competitors", action="store_true")
    parser.add_argument("--target-file", type=Path, default=DEFAULT_TARGET_FILE)
    parser.add_argument("--baseline-json", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--append-tsv", type=Path, default=DEFAULT_RESULTS_TSV)
    parser.add_argument("--note", default="")
    return parser.parse_args()


def ensure_secret(env: Dict[str, str], key: str, fallback: str) -> None:
    current = str(env.get(key, "")).strip()
    if len(current) >= MIN_SECRET_LENGTH:
        return
    env[key] = fallback


def pp_ocr_python_path(pp_ocr_root: Path, override: Optional[Path]) -> Path:
    if override is not None:
        return Path(os.path.abspath(os.fspath(override)))
    return Path(os.path.abspath(os.fspath(pp_ocr_root / ".venv" / "bin" / "python")))


def pp_ocr_git_head(pp_ocr_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(pp_ocr_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()
    except Exception:
        return "unknown"


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_latest_baseline_json(pp_ocr_root: Path, dataset_name: str) -> Optional[Path]:
    research_dir = pp_ocr_root / "data" / "research_results"
    if not research_dir.exists():
        return None

    candidates = sorted(research_dir.glob("unified_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            payload = load_json(path)
        except Exception:
            continue
        if str(payload.get("dataset", "")).strip() != dataset_name:
            continue
        results = payload.get("results") or {}
        if all(method in results for method in COMPETITOR_METHODS):
            return path
    return None


def load_targets_file(path: Path) -> Dict[str, Dict[str, Any]]:
    payload = load_json(path)
    targets = payload.get("targets")
    if not isinstance(targets, dict):
        raise ValueError(f"targets file is missing a 'targets' object: {path}")

    result: Dict[str, Dict[str, Any]] = {}
    for method in COMPETITOR_METHODS:
        value = targets.get(method)
        if isinstance(value, dict):
            result[method] = dict(value)
    return result


def compact_metric_bundle(metrics: Dict[str, Any], speed: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "row_accuracy": metrics.get("row_accuracy"),
        "column_accuracy": metrics.get("column_accuracy"),
        "cell_f1": metrics.get("cell_f1"),
        "mean_cell_cer": metrics.get("mean_cell_cer"),
        "teds": metrics.get("teds"),
        "teds_struct": metrics.get("teds_struct"),
        "composite_score": metrics.get("composite_score"),
        "core_ms": speed.get("mean_ms"),
        "e2e_ms": speed.get("mean_ms"),
        "count": metrics.get("count"),
    }


def build_inline_eval_code() -> str:
    return textwrap.dedent(
        f"""
        import json
        import sys
        from pathlib import Path

        from app.benchmark.research_dataset import load_gt_entries
        from app.benchmark.research_methods import external_method_availability
        from app.benchmark.research_suites import build_external_method_specs, run_method_suite
        from app.invision.workflows.research_table import build_internal_method_specs

        dataset = Path(sys.argv[1]).resolve()
        max_samples = int(sys.argv[2])
        sample_start = int(sys.argv[3])
        selected_methods = [item for item in sys.argv[4].split(",") if item]

        gt_entries = load_gt_entries(dataset)
        method_specs = {{}}
        method_specs.update(build_internal_method_specs())
        method_specs.update(build_external_method_specs(
            external_method_availability=external_method_availability,
        ))
        method_specs = {{
            key: value
            for key, value in method_specs.items()
            if key in selected_methods
        }}

        run_stats = run_method_suite(
            gt_entries=gt_entries,
            method_specs=method_specs,
            dataset_dir=dataset,
            max_samples=max_samples,
            sample_start=sample_start,
            use_real_ocr=True,
            include_statistics=True,
            check_cancelled=lambda: None,
        )
        summary = {{
            "dataset": str(dataset),
            "available_methods": list(method_specs.keys()),
            "metrics": run_stats.get("metrics", {{}}),
            "speed": run_stats.get("speed", {{}}),
            "requested_samples": run_stats.get("requested_samples", 0),
            "evaluated_samples": run_stats.get("evaluated_samples", 0),
            "skipped_samples": run_stats.get("skipped_samples", 0),
            "analysis": run_stats.get("analysis", {{}}),
        }}
        print("{JSON_SENTINEL}" + json.dumps(summary, ensure_ascii=False))
        """
    ).strip()


def parse_subprocess_json(output: str) -> Dict[str, Any]:
    for line in reversed(output.splitlines()):
        if line.startswith(JSON_SENTINEL):
            return json.loads(line[len(JSON_SENTINEL):])
    raise RuntimeError("pp-ocr benchmark JSON sentinel not found in subprocess output.")


def run_live_eval(
    *,
    pp_ocr_root: Path,
    dataset: Path,
    python_path: Path,
    proposed_method: str,
    max_samples: int,
    sample_start: int,
    run_live_competitors: bool,
) -> Dict[str, Any]:
    selected_methods = [proposed_method]
    if run_live_competitors:
        selected_methods.extend(COMPETITOR_METHODS)

    env = os.environ.copy()
    ensure_secret(env, "OCR_JWT_SECRET_KEY", "autoresearch-local-jwt-secret-key-abcdefghijklmnopqrstuvwxyz")
    ensure_secret(env, "OCR_REFRESH_SECRET_KEY", "autoresearch-local-refresh-secret-key-abcdefghijklmnopqrstuvwxyz")

    proc = subprocess.run(
        [
            str(python_path),
            "-c",
            build_inline_eval_code(),
            str(dataset),
            str(max_samples),
            str(sample_start),
            ",".join(selected_methods),
        ],
        cwd=str(pp_ocr_root),
        env=env,
        capture_output=True,
        text=True,
    )
    combined_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise RuntimeError(
            "pp-ocr live benchmark failed.\n"
            f"Command: {python_path} -c <inline>\n"
            f"Output:\n{combined_output.strip()}"
        )

    payload = parse_subprocess_json(proc.stdout or "")
    payload["raw_output"] = combined_output
    return payload


def comparison_row(candidate: Dict[str, Any], target: Dict[str, Any], *, lower_is_better: bool) -> Dict[str, Any]:
    candidate_value = candidate.get("value")
    target_value = target.get("value")
    if candidate_value is None or target_value is None:
        return {
            "candidate": candidate_value,
            "target": target_value,
            "delta": None,
            "meets_target": False,
        }

    candidate_num = float(candidate_value)
    target_num = float(target_value)
    if lower_is_better:
        delta = target_num - candidate_num
        meets_target = candidate_num <= target_num
    else:
        delta = candidate_num - target_num
        meets_target = candidate_num >= target_num
    return {
        "candidate": candidate_num,
        "target": target_num,
        "delta": round(delta, 6),
        "meets_target": bool(meets_target),
    }


def build_head_to_head(candidate: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    metric_names = (
        ("row_accuracy", False),
        ("column_accuracy", False),
        ("cell_f1", False),
        ("mean_cell_cer", True),
        ("teds", False),
        ("teds_struct", False),
        ("composite_score", False),
        ("core_ms", True),
        ("e2e_ms", True),
    )
    return {
        metric: comparison_row(
            {"value": candidate.get(metric)},
            {"value": target.get(metric)},
            lower_is_better=lower_is_better,
        )
        for metric, lower_is_better in metric_names
    }


def ensure_tsv_header(path: Path) -> None:
    if path.exists():
        return
    path.write_text(
        "\t".join(
            [
                "timestamp",
                "pp_ocr_commit",
                "dataset",
                "max_samples",
                "sample_start",
                "proposed_method",
                "proposed_teds",
                "proposed_teds_struct",
                "proposed_cell_f1",
                "proposed_cer",
                "proposed_row_accuracy",
                "proposed_column_accuracy",
                "proposed_core_ms",
                "paddle_teds_target",
                "paddle_core_ms_target",
                "glm_teds_target",
                "glm_core_ms_target",
                "live_methods",
                "baseline_json",
                "note",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def append_tsv_row(
    *,
    path: Path,
    timestamp: str,
    pp_ocr_commit: str,
    dataset: str,
    max_samples: int,
    sample_start: int,
    proposed_method: str,
    proposed_metrics: Dict[str, Any],
    baseline_metrics: Dict[str, Dict[str, Any]],
    live_methods: Iterable[str],
    baseline_json: Optional[Path],
    note: str,
) -> None:
    ensure_tsv_header(path)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            [
                timestamp,
                pp_ocr_commit,
                dataset,
                max_samples,
                sample_start,
                proposed_method,
                proposed_metrics.get("teds"),
                proposed_metrics.get("teds_struct"),
                proposed_metrics.get("cell_f1"),
                proposed_metrics.get("mean_cell_cer"),
                proposed_metrics.get("row_accuracy"),
                proposed_metrics.get("column_accuracy"),
                proposed_metrics.get("core_ms"),
                baseline_metrics.get("external_paddleocr_vl", {}).get("teds"),
                baseline_metrics.get("external_paddleocr_vl", {}).get("core_ms"),
                baseline_metrics.get("external_glm_ocr", {}).get("teds"),
                baseline_metrics.get("external_glm_ocr", {}).get("core_ms"),
                ",".join(live_methods),
                str(baseline_json) if baseline_json is not None else "",
                note,
            ]
        )


def main() -> int:
    args = parse_args()
    pp_ocr_root = args.pp_ocr_root.resolve()
    dataset = args.dataset.resolve()
    python_path = pp_ocr_python_path(pp_ocr_root, args.pp_ocr_python)
    output_path = args.output.resolve()
    tsv_path = args.append_tsv.resolve()
    target_file = args.target_file.resolve()

    if not pp_ocr_root.exists():
        raise SystemExit(f"pp-ocr root not found: {pp_ocr_root}")
    if not dataset.exists():
        raise SystemExit(f"dataset not found: {dataset}")
    if not python_path.exists():
        raise SystemExit(f"pp-ocr python not found: {python_path}")

    baseline_metrics: Dict[str, Dict[str, Any]] = {}
    dataset_name = dataset.name
    targets_source: Optional[Path] = None

    if target_file.exists():
        baseline_metrics = load_targets_file(target_file)
        targets_source = target_file
    else:
        baseline_json = args.baseline_json.resolve() if args.baseline_json is not None else find_latest_baseline_json(
            pp_ocr_root, dataset_name
        )
        baseline_speed: Dict[str, Dict[str, Any]] = {}
        if baseline_json is not None and baseline_json.exists():
            baseline_payload = load_json(baseline_json)
            baseline_results = baseline_payload.get("results") or {}
            baseline_speed = baseline_payload.get("speed") or {}
            for method in COMPETITOR_METHODS:
                baseline_metrics[method] = compact_metric_bundle(
                    baseline_results.get(method, {}),
                    baseline_speed.get(method, {}),
                )
            targets_source = baseline_json

    live_payload = run_live_eval(
        pp_ocr_root=pp_ocr_root,
        dataset=dataset,
        python_path=python_path,
        proposed_method=args.proposed_method,
        max_samples=args.max_samples,
        sample_start=args.sample_start,
        run_live_competitors=args.run_live_competitors,
    )

    live_metrics = live_payload.get("metrics") or {}
    live_speed = live_payload.get("speed") or {}
    proposed_metrics = compact_metric_bundle(
        live_metrics.get(args.proposed_method, {}),
        live_speed.get(args.proposed_method, {}),
    )

    live_competitor_metrics: Dict[str, Dict[str, Any]] = {}
    for method in COMPETITOR_METHODS:
        if method in live_metrics:
            live_competitor_metrics[method] = compact_metric_bundle(
                live_metrics.get(method, {}),
                live_speed.get(method, {}),
            )

    effective_targets = dict(baseline_metrics)
    effective_targets.update(live_competitor_metrics)

    timestamp = datetime.now(timezone.utc).astimezone().isoformat()
    pp_ocr_commit = pp_ocr_git_head(pp_ocr_root)

    summary = {
        "timestamp": timestamp,
        "pp_ocr_root": str(pp_ocr_root),
        "pp_ocr_commit": pp_ocr_commit,
        "dataset": str(dataset),
        "dataset_name": dataset_name,
        "max_samples": args.max_samples,
        "sample_start": args.sample_start,
        "proposed_method": args.proposed_method,
        "note": args.note,
        "live": {
            "available_methods": live_payload.get("available_methods", []),
            "requested_samples": live_payload.get("requested_samples"),
            "evaluated_samples": live_payload.get("evaluated_samples"),
            "skipped_samples": live_payload.get("skipped_samples"),
            "proposed": proposed_metrics,
            "competitors": live_competitor_metrics,
        },
        "targets": {
            "baseline_json": str(targets_source) if targets_source is not None else None,
            "target_file": str(target_file) if target_file.exists() else None,
            "competitors": effective_targets,
        },
        "head_to_head": {
            method: build_head_to_head(proposed_metrics, target_metrics)
            for method, target_metrics in effective_targets.items()
        },
    }

    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    append_tsv_row(
        path=tsv_path,
        timestamp=timestamp,
        pp_ocr_commit=pp_ocr_commit,
        dataset=dataset_name,
        max_samples=args.max_samples,
        sample_start=args.sample_start,
        proposed_method=args.proposed_method,
        proposed_metrics=proposed_metrics,
        baseline_metrics=effective_targets,
        live_methods=live_payload.get("available_methods", []),
        baseline_json=targets_source,
        note=args.note,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
