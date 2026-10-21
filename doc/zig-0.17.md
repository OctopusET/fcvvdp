# Zig 0.17 upgrade validation

Version 0.4.1 requires Zig 0.17.x. It pins `simpleimgio` main at
`98473d19f243eefd4ef29a2149af47bc072c2484` and the Zig 0.17 libspng wrapper from
[libspng PR #1](https://github.com/gianni-rosato/libspng/pull/1). The metric's C
implementation and C compiler optimization flags are unchanged.

The AVX2/FMA implementation now has a separate build module with those CPU
features enabled. The dispatcher and scalar implementation retain the requested
target CPU, so generic x86_64 builds work without enabling AVX globally.

`-Dflto=true` selects LLD and full LTO for the library, SIMD object, CLI, and
C API test executable on ELF targets. Zig cannot use this LTO path for Mach-O;
macOS requests now fail with an explicit message. The original Zig 0.16 baseline
also fails to build with `-Dflto=true` on macOS.

## Correctness

`zig build test` runs 22 dependency tests, a C API test executable, and 85 CLI
metric cases. Fixtures cover odd dimensions, grayscale/alpha/RGB/RGBA PNGs at
8/16 bits, all six classic Netpbm encodings, four PAM channel layouts, RGB/RGBA
QOI, and full/limited-range Y4M at 8/9/10/12/16 bits with chroma siting metadata.
The CLI cases include all 27 display presets, identical inputs, and one/four
threads. Twelve invalid-input cases and help/text output are also checked.

The C tests cover equivalent 8/16-bit and linear float inputs, a larger odd-sized
image that enables threaded work, temporal reset, display parameters, and API
errors. Checks remain active in release builds. They also pass when linked to
the original Zig 0.16 library.

`tests/expected.json` was recorded from unmodified fcvvdp commit
`98bd21a7a876be29ba06a29325b03624047ee850`, built with Zig 0.16.0 / ReleaseFast.
JSON fields and metadata must match exactly. Numerical checks permit 0.000002
absolute JOD error and 10 ppm relative internal-quality error (with a 0.000002
absolute floor) for compiler, optimization-mode, libm, and SIMD rounding.
The C float conversion comparison permits 20 ppm in internal quality because
the caller's strict conversion and the library's fast-math conversion can round
differently before the metric.

On arm64 macOS 27.0.1, the final Zig 0.17 release binary differs from the Zig
0.16 baseline by at most **0.000001 JOD** and **0.000012 internal quality**
(3.08 ppm relative quality) across all 85 cases. Identical inputs still score
10 JOD and zero quality. These are bounded numerical comparisons, not a claim
of bitwise equality or proof for every possible input.

Local validation includes debug/safe/fast/small on arm64 macOS, the full release
suite on x86_64 macOS under Rosetta, and generic x86_64 Linux release cross-builds
with and without LTO. CI covers all four modes on Linux and macOS plus Linux LTO.

## Reproducing a baseline comparison

Install Zig 0.16.0 separately alongside Zig 0.17.0. From this checkout:

```sh
mkdir -p /tmp/fcvvdp-baseline
git archive 98bd21a7a876be29ba06a29325b03624047ee850 | tar -x -C /tmp/fcvvdp-baseline
(cd /tmp/fcvvdp-baseline && /path/to/zig-0.16.0/zig build --release=fast)
zig build --release=fast
python3 tests/regression.py zig-out/bin/fcvvdp \
  --baseline /tmp/fcvvdp-baseline/zig-out/bin/fcvvdp
python3 bench/compare.py /tmp/fcvvdp-baseline/zig-out/bin/fcvvdp \
  zig-out/bin/fcvvdp --samples 24 --output /tmp/fcvvdp-performance.json
```

The benchmark requires Python 3 and `/usr/bin/time` (BSD time on macOS or GNU
time on Linux). It generates deterministic 1080p PNG and 16-bit PPM images,
eight-frame 360p 8/10-bit Y4M clips, and four-frame 720p 10-bit Y4M clips.
Videos run with one and four threads. Setup and fixture encoding are excluded;
process startup, decoding, conversion, metric computation, and teardown are
included. Filesystem caches are warmed before measurement.

Each sample alternates binary order, rotates workload order, and validates both
scores and metadata. Reports retain every wall-time/RSS measurement, per-case
results, input/binary SHA-256 hashes, paired geometric mean ratios, and bootstrap
95% confidence intervals. The configurable slowdown limit defaults to 1%; a
regression or an inconclusive interval returns a nonzero status. Passing that
limit does not establish literally zero performance regression.

## Measured performance

On arm64 macOS 27.0.1, 24 alternating paired measurements of the final pinned
release binary against Zig 0.16.0 / ReleaseFast gave the following wall-time
changes (negative is faster):

| Workload | Paired change | Bootstrap 95% interval |
| --- | ---: | ---: |
| 1080p PNG | -0.88% | -1.62% to -0.19% |
| 1080p 16-bit PPM | -1.19% | -1.62% to -0.73% |
| 360p 8-bit Y4M, 1 thread | +0.01% | -0.43% to +0.48% |
| 360p 8-bit Y4M, 4 threads | +0.06% | -0.12% to +0.23% |
| 360p 10-bit Y4M, 1 thread | +0.31% | -0.08% to +0.66% |
| 360p 10-bit Y4M, 4 threads | +0.03% | -0.25% to +0.28% |
| 720p 10-bit Y4M, 1 thread | +0.38% | -0.02% to +0.76% |
| 720p 10-bit Y4M, 4 threads | +0.18% | -0.10% to +0.44% |

No workload shows a statistically resolved runtime slowdown in this run; the
largest upper confidence bound is +0.76%. Peak RSS increases by 32–48 KiB
(at most 0.05%). This small memory increase means the result does **not** meet
a literal zero-regression requirement. Other hosts, inputs, and long-running
workloads still need their own measurements.

The measured baseline binary SHA-256 is
`a5a942f6f5cd6e4b0767f9f9fbc48e29e484a9d02eed5d9dc7cb5001a4dfa4d8`;
the candidate binary SHA-256 is
`355cdf3747ac4223a1035b8018adeaa096003ef0966f6813ec251a8088e7760e`.
