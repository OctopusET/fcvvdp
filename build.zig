const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const strip = b.option(bool, "strip", "strip symbols from the binary, defaults to false") orelse false;
    const flto = b.option(bool, "flto", "enable Link Time Optimization on ELF targets, defaults to false") orelse false;
    if (flto and target.result.ofmt != .elf) {
        const unsupported = b.addFail("Zig 0.17 supports this project's LTO build only on ELF targets; omit -Dflto=true for macOS");
        b.default_step.dependOn(&unsupported.step);
        return;
    }
    const options = b.addOptions();

    const simpleimgio_dep = b.dependency("simpleimgio", .{
        .target = target,
        .optimize = optimize,
    });
    const simpleimgio = simpleimgio_dep.module("simpleimgio");

    const spng_dep = b.dependency("spng", .{
        .target = target,
        .optimize = optimize,
    });
    const spng = spng_dep.artifact("spng");

    const translate_c = b.addTranslateC(.{
        .root_source_file = b.path("c_imports.h"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    translate_c.addIncludePath(b.path("."));
    translate_c.addIncludePath(spng.getEmittedIncludeTree());
    const c_module = translate_c.createModule();

    const cvvdp = b.addLibrary(.{
        .name = "cvvdp",
        .use_lld = if (flto) true else null,
        .root_module = b.createModule(.{
            .target = target,
            .optimize = optimize,
            .link_libc = true,
            .strip = strip,
        }),
    });
    const cvvdp_sources = [_][]const u8{
        "src/cvvdp.c",
        "src/cvvdp_c.c",
    };
    const cvvdp_flags = [_][]const u8{
        "-std=c23",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-O3",
        "-ffast-math",
    };
    const target_result = target.result;
    cvvdp.root_module.addCSourceFiles(.{
        .files = &cvvdp_sources,
        .flags = &cvvdp_flags,
    });

    if (target_result.cpu.arch == .x86_64) {
        var avx2_query = target.query;
        avx2_query.cpu_features_sub.removeFeature(@backingInt(std.Target.x86.Feature.avx2));
        avx2_query.cpu_features_sub.removeFeature(@backingInt(std.Target.x86.Feature.fma));
        avx2_query.cpu_features_add.addFeature(@backingInt(std.Target.x86.Feature.avx2));
        avx2_query.cpu_features_add.addFeature(@backingInt(std.Target.x86.Feature.fma));
        const avx2_module = b.createModule(.{
            .target = b.resolveTargetQuery(avx2_query),
            .optimize = optimize,
            .link_libc = true,
            .strip = strip,
        });
        avx2_module.addIncludePath(b.path("."));
        avx2_module.addCSourceFile(.{
            .file = b.path("src/cvvdp_avx2.c"),
            .flags = &cvvdp_flags,
        });
        const avx2 = b.addObject(.{
            .name = "cvvdp-avx2",
            .root_module = avx2_module,
            .use_lld = if (flto) true else null,
        });
        avx2.lto = if (flto) .full else null;
        cvvdp.root_module.addObject(avx2);
    } else if (target_result.cpu.arch == .aarch64) {
        cvvdp.root_module.addCSourceFile(.{
            .file = b.path("src/cvvdp_neon.c"),
            .flags = &cvvdp_flags,
        });
    }
    cvvdp.root_module.addIncludePath(b.path("."));
    cvvdp.lto = if (flto) .full else null;
    b.installArtifact(cvvdp);

    cvvdp.installHeader(b.path("src/cvvdp.h"), "cvvdp.h");

    const cvvdpenc = b.addExecutable(.{
        .name = "fcvvdp",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .link_libc = true,
            .strip = strip,
        }),
        .use_llvm = true,
        .use_lld = if (flto) true else null,
    });
    cvvdpenc.root_module.addOptions("build_opts", options);
    cvvdpenc.root_module.addImport("c", c_module);
    cvvdpenc.root_module.addImport("simpleimgio", simpleimgio);
    cvvdpenc.root_module.addIncludePath(b.path("."));
    cvvdpenc.root_module.linkLibrary(cvvdp);
    cvvdpenc.root_module.linkLibrary(spng);
    cvvdpenc.lto = if (flto) .full else null;
    b.installArtifact(cvvdpenc);
}
