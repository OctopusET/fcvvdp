#!/usr/bin/env python3
"""Compare release CLI binaries using paired end-to-end time and peak RSS."""

import argparse
import hashlib
import json
import math
import platform
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from fixtures import pixels, png, y4m
from regression import compare


def inputs(directory):
    cases = {}
    for label, distorted in (("ref", False), ("dis", True)):
        rgb = pixels(1920, 1080, distorted)
        png(directory / f"{label}.png", 1920, 1080, rgb)
        data = bytearray()
        for value in rgb:
            data.extend(bytes([value, value]))
        (directory / f"{label}.ppm").write_bytes(b"P6\n1920 1080\n65535\n" + data)
        for width, height, frames, bits in ((640, 360, 8, 8), (640, 360, 8, 10), (1280, 720, 4, 10)):
            name = f"{width}x{height}-{bits}"
            y4m(directory / f"{label}-{name}.y4m", width, height, frames, bits,
                "420jpeg" if bits == 8 else "420p10", distorted=distorted)
            if label == "ref":
                for threads in (1, 4):
                    cases[f"y4m-{name}-t{threads}"] = ["-t", str(threads), f"ref-{name}.y4m", f"dis-{name}.y4m"]
    return {"png-1080p": ["ref.png", "dis.png"],
            "ppm16-1080p": ["ref.ppm", "dis.ppm"], **cases}


def measure(binary, args, directory):
    timer = ["/usr/bin/time", "-l" if sys.platform == "darwin" else "-v"]
    start = time.perf_counter_ns()
    run = subprocess.run([*timer, str(binary), "-j", *args], cwd=directory,
                         capture_output=True, text=True, timeout=180)
    elapsed = time.perf_counter_ns() - start
    if run.returncode:
        raise RuntimeError(run.stderr)
    result, _ = json.JSONDecoder().raw_decode(run.stderr[run.stderr.index("{"):])
    pattern = (r"(\d+)\s+maximum resident set size" if sys.platform == "darwin"
               else r"Maximum resident set size \(kbytes\):\s*(\d+)")
    rss = int(re.search(pattern, run.stderr).group(1))
    if sys.platform != "darwin":
        rss *= 1024
    return {"wall_ns": elapsed, "peak_rss_bytes": rss, "result": result}


def summarize(pairs, key, limit, rng):
    a = [p["baseline"][key] for p in pairs]
    b = [p["candidate"][key] for p in pairs]
    ratios = [math.log(y / x) for x, y in zip(a, b)]
    bootstrap = sorted(math.exp(statistics.mean(rng.choices(ratios, k=len(ratios))))
                       for _ in range(10000))
    low, high = bootstrap[250], bootstrap[9749]
    return {"baseline_median": statistics.median(a), "candidate_median": statistics.median(b),
            "paired_ratio": math.exp(statistics.mean(ratios)), "ratio_ci95": [low, high],
            "verdict": "pass" if high <= limit else "regression" if low > limit else "inconclusive"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=lambda p: Path(p).resolve())
    parser.add_argument("candidate", type=lambda p: Path(p).resolve())
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--threshold", type=float, default=1.0, help="Upper confidence bound slowdown limit, percent")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 8 or not math.isfinite(args.threshold) or args.threshold < 0:
        parser.error("Require at least 8 samples and a finite, nonnegative threshold")
    rng = random.Random(42)
    report = {"host": platform.platform(), "processor": platform.machine(),
              "samples": args.samples, "threshold_percent": args.threshold,
              "binaries": {k: {"path": str(getattr(args, k)), "sha256": sha256(getattr(args, k))}
                           for k in ("baseline", "candidate")}, "results": {}, "raw_samples": {}}
    with tempfile.TemporaryDirectory(prefix="fcvvdp-bench-") as tmp:
        directory = Path(tmp)
        print("Generating 1080p image and 360p/720p video fixtures...", flush=True)
        cases = inputs(directory)
        report["input_sha256"] = {p.name: sha256(p) for p in sorted(directory.iterdir())}
        expected = {}
        for name, case in cases.items():
            expected[name] = measure(args.baseline, case, directory)["result"]
            compare(measure(args.candidate, case, directory)["result"], expected[name], name)
            report["raw_samples"][name] = []
        for index in range(args.samples):
            # Alternate program order and rotate case order to limit drift bias.
            names = list(cases)
            names = names[index % len(names):] + names[:index % len(names)]
            for name in names:
                pair = {}
                order = ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
                for label in order:
                    pair[label] = measure(getattr(args, label), cases[name], directory)
                    compare(pair[label]["result"], expected[name], name)
                report["raw_samples"][name].append(pair)
            print(f"Completed pair {index + 1}/{args.samples}", flush=True)
    status = 0
    for name, pairs in report["raw_samples"].items():
        result = {key: summarize(pairs, key, 1 + args.threshold / 100, rng)
                  for key in ("wall_ns", "peak_rss_bytes")}
        report["results"][name] = result
        for key, stats in result.items():
            if stats["verdict"] != "pass":
                status = max(status, 1 if stats["verdict"] == "regression" else 2)
            print(f"{name:25} {key:15} {100 * (stats['paired_ratio'] - 1):+7.2f}%"
                  f" 95% CI [{100 * (stats['ratio_ci95'][0] - 1):+.2f}%,"
                  f" {100 * (stats['ratio_ci95'][1] - 1):+.2f}%] {stats['verdict']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
