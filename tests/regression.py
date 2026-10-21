#!/usr/bin/env python3
"""Exercise CLI decoding, metric results, threading, presets, and error paths."""

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
from fixtures import generate


MODELS = ("fhd", "4k", "hdr_pq", "hdr_hlg", "hdr_linear", "hdr_dark", "hdr_zoom",
          "standard_hmd", "standard_phone", "sdr_4k_30", "sdr_fhd_24", "htc_vive_pro",
          "iphone_12_pro", "iphone_14_pro", "iphone_14_pro_vert", "iphone_14_pro_hdr",
          "iphone_14_pro_hdr_vert", "ipad_pro_12_9", "macbook_pro_16", "lg_oled_2017_sdr",
          "lg_oled_2017_hdr", "eizo_CG3146", "65inch_hdr_pq_4knit", "65inch_hdr_pq_2knit",
          "65inch_hdr_pq_1knit", "lg_oled_2026_hdr_pq", "mcos")


def cases():
    result = {}
    for color in (0, 2, 4, 6):
        for bits in (8, 16):
            suffix = f"-png{color}-{bits}.png"
            result[f"png-{color}-{bits}"] = ["ref" + suffix, "dis" + suffix]
    result["qoi"] = ["ref.qoi", "dis.qoi"]
    result["qoi-rgba"] = ["ref-rgba.qoi", "dis-rgba.qoi"]
    for magic in ("P1", "P4"):
        result[magic] = [f"ref-{magic}.pbm", f"dis-{magic}.pbm"]
    for magic, ext in (("P2", "pgm"), ("P3", "ppm"), ("P5", "pgm"), ("P6", "ppm")):
        for maximum in (255, 1023, 65535):
            suffix = f"-{magic}-{maximum}.{ext}"
            result[f"{magic}-{maximum}"] = ["ref" + suffix, "dis" + suffix]
    for channels in (1, 2, 3, 4):
        result[f"pam-{channels}"] = [f"ref-{channels}.pam", f"dis-{channels}.pam"]
    for chroma in ("420jpeg", "420mpeg2", "420paldv", "420p9", "420p10", "420p12", "420p16"):
        for full in (False, True):
            for threads in (1, 4):
                suffix = f"-{chroma}-{full}.y4m"
                result[f"y4m-{chroma}-{full}-t{threads}"] = ["-t", str(threads), "ref" + suffix, "dis" + suffix]
    for model in MODELS:
        result[f"model-{model}"] = ["-m", model, "ref.qoi", "dis.qoi"]
    result["identical-image"] = ["ref.qoi", "ref.qoi"]
    result["identical-video"] = ["-t", "1", "ref-420jpeg-False.y4m", "ref-420jpeg-False.y4m"]
    return result


def invoke(binary, args, directory):
    return subprocess.run([str(binary), *args], cwd=directory, capture_output=True,
                          text=True, timeout=60)


def metric(binary, args, directory):
    run = invoke(binary, ["-j", *args], directory)
    if run.returncode:
        raise AssertionError(f"{args}: exit {run.returncode}\n{run.stdout}{run.stderr}")
    # The established CLI prints its banner and JSON on stderr.
    text = run.stderr
    data = json.loads(text[text.index("{"):])
    for key in ("jod", "quality"):
        if not math.isfinite(data[key]):
            raise AssertionError(f"{args}: non-finite {key}")
    return data


def compare(actual, expected, name):
    if actual.keys() != expected.keys():
        raise AssertionError(f"{name}: JSON fields differ")
    for key, value in expected.items():
        # Fixed limits for compiler/libm/SIMD rounding: 2 micro-JOD and
        # 10 parts per million in the internal quality accumulator.
        equal = (math.isclose(actual[key], value, rel_tol=0, abs_tol=2e-6)
                 if key == "jod" else
                 math.isclose(actual[key], value, rel_tol=1e-5, abs_tol=2e-6)
                 if key == "quality" else actual[key] == value)
        if not equal:
            raise AssertionError(f"{name}.{key}: {actual[key]!r} != {value!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=lambda p: Path(p).resolve())
    parser.add_argument("--baseline", type=lambda p: Path(p).resolve())
    parser.add_argument("--record", type=Path, help="Record snapshots from a trusted baseline")
    args = parser.parse_args()
    golden_path = Path(__file__).with_name("expected.json")
    golden = {} if args.record else json.loads(golden_path.read_text())
    outputs = {}
    with tempfile.TemporaryDirectory(prefix="fcvvdp-regression-") as tmp:
        directory = generate(tmp)
        for name, case in cases().items():
            actual = metric(args.binary, case, directory)
            if args.baseline:
                compare(actual, metric(args.baseline, case, directory), name)
            if not args.record:
                compare(actual, golden[name], name)
            outputs[name] = actual
        for threads in (1, 4):
            for chroma in ("420jpeg", "420mpeg2", "420paldv", "420p9", "420p10", "420p12", "420p16"):
                for full in (False, True):
                    compare(outputs[f"y4m-{chroma}-{full}-t{threads}"],
                            outputs[f"y4m-{chroma}-{full}-t1"], "thread parity")
        for name in ("identical-image", "identical-video"):
            if outputs[name]["jod"] != 10 or outputs[name]["quality"] != 0:
                raise AssertionError(f"{name}: identical inputs must score 10 JOD / 0 quality")
        errors = [([], "MissingFiles"), (["--unknown"], "UnknownOption"),
                  (["-m"], "InvalidArguments"), (["-t"], "InvalidArguments"),
                  (["ref.qoi", "dis.qoi", "ref.qoi"], "TooManyFiles"),
                  (["ref.qoi", "ref-420jpeg-False.y4m"], "MismatchedInputTypes"),
                  (["ref.qoi", "wrong-size.png"], "DimensionMismatch"),
                  (["ref-420jpeg-False.y4m", "short.y4m"], "FrameCountMismatch"),
                  (["empty.y4m", "empty.y4m"], "EmptyY4M"),
                  (["missing.png", "dis.qoi"], "FileNotFound"),
                  (["bad.png", "dis.qoi"], "GetHeaderFailed")]
        errors.append((["bad.ppm", "dis.qoi"], "InsufficientData"))
        for case, error in errors:
            run = invoke(args.binary, case, directory)
            if run.returncode <= 0 or f"error: {error}" not in run.stderr:
                raise AssertionError(f"{case}: expected {error}, got {run.returncode}\n{run.stderr}")
        for option in ("-h", "--help"):
            run = invoke(args.binary, [option], directory)
            if run.returncode or "usage: fcvvdp" not in run.stderr:
                raise AssertionError(f"{option}: help failed")
        for option in ([], ["-v"]):
            run = invoke(args.binary, [*option, "ref.qoi", "dis.qoi"], directory)
            if run.returncode or ("JOD Score:" if option else "JOD:") not in run.stderr:
                raise AssertionError(f"{option}: text output failed")
    if args.record:
        args.record.write_text(json.dumps(outputs, indent=2) + "\n")
    print(f"{len(outputs)} metric cases, {len(errors)} error paths, help/text output and thread parity passed")


if __name__ == "__main__":
    main()
