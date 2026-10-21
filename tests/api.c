#include "cvvdp.h"
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(expr) do { if (!(expr)) { \
    fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #expr); \
    exit(1); \
} } while (0)

static void same_result(FcvvdpResult a, FcvvdpResult b)
{
    if (fabs(a.jod - b.jod) >= 0.000002 ||
        fabs(a.quality - b.quality) >= 0.00001 * fmax(1, fabs(b.quality)))
        fprintf(stderr, "results: %.12g / %.12g versus %.12g / %.12g\n",
                a.jod, a.quality, b.jod, b.quality);
    CHECK(isfinite(a.jod) && isfinite(a.quality));
    CHECK(fabs(a.jod - b.jod) < 0.000002);
    CHECK(fabs(a.quality - b.quality) < 0.00001 * fmax(1, fabs(b.quality)));
}

static float linear(uint8_t sample)
{
    const float value = sample / 255.0f;
    return value <= 0.04045f ? value / 12.92f : powf((value + 0.055f) / 1.055f, 2.4f);
}

int main(void)
{
    CHECK(strcmp(cvvdp_version_string(), "0.4.1") == 0);
    /* Odd dimensions exercise vector tails; >16384 pixels enables pool work. */
    enum { W = 193, H = 129, N = W * H * 3 };
    uint8_t reference[N], distorted[N];
    uint16_t ref16[N], dis16[N];
    float ref_float[N], dis_float[N];
    for (int i = 0; i < N; i++) {
        reference[i] = (uint8_t)(i * 17 + i / 31);
        distorted[i] = (uint8_t)(reference[i] ^ 7);
        ref16[i] = reference[i] * 257;
        dis16[i] = distorted[i] * 257;
        ref_float[i] = linear(reference[i]);
        dis_float[i] = linear(distorted[i]);
    }
    FcvvdpImage ref = {W, H, W * 3, reference, CVVDP_PIXEL_FORMAT_RGB_UINT8, CVVDP_COLORSPACE_SRGB};
    FcvvdpImage dis = {W, H, W * 3, distorted, CVVDP_PIXEL_FORMAT_RGB_UINT8, CVVDP_COLORSPACE_SRGB};
    FcvvdpResult expected, actual;
    CHECK(cvvdp_compare_images(&ref, &dis, CVVDP_DISPLAY_STANDARD_FHD, 1, NULL, &expected) == CVVDP_OK);
    CHECK(expected.jod > 0 && expected.jod < 10 && expected.quality > 0);
    CHECK(cvvdp_compare_images(&ref, &dis, CVVDP_DISPLAY_STANDARD_FHD, 4, NULL, &actual) == CVVDP_OK);
    same_result(actual, expected);
    CHECK(cvvdp_compare_images(&ref, &ref, CVVDP_DISPLAY_STANDARD_FHD, 1, NULL, &actual) == CVVDP_OK);
    CHECK(actual.jod == 10 && actual.quality == 0);

    FcvvdpImage r16 = {W, H, W * 6, ref16, CVVDP_PIXEL_FORMAT_RGB_UINT16, CVVDP_COLORSPACE_SRGB};
    FcvvdpImage d16 = {W, H, W * 6, dis16, CVVDP_PIXEL_FORMAT_RGB_UINT16, CVVDP_COLORSPACE_SRGB};
    CHECK(cvvdp_compare_images(&r16, &d16, CVVDP_DISPLAY_STANDARD_FHD, 1, NULL, &actual) == CVVDP_OK);
    same_result(actual, expected);
    FcvvdpImage rf = {W, H, W * 12, ref_float, CVVDP_PIXEL_FORMAT_RGB_FLOAT, CVVDP_COLORSPACE_LINEAR};
    FcvvdpImage df = {W, H, W * 12, dis_float, CVVDP_PIXEL_FORMAT_RGB_FLOAT, CVVDP_COLORSPACE_LINEAR};
    CHECK(cvvdp_compare_images(&rf, &df, CVVDP_DISPLAY_STANDARD_FHD, 1, NULL, &actual) == CVVDP_OK);
    /* The caller's strict sRGB conversion and the library's fast-math
       conversion can round differently before the nonlinear metric. */
    CHECK(fabs(actual.jod - expected.jod) < 0.000002);
    CHECK(fabs(actual.quality - expected.quality) < 0.00002 * expected.quality);
    FcvvdpResult float_expected = actual;
    CHECK(cvvdp_compare_images(&rf, &df, CVVDP_DISPLAY_STANDARD_FHD, 4, NULL, &actual) == CVVDP_OK);
    same_result(actual, float_expected);

    for (unsigned threads = 1; threads <= 4; threads += 3) {
        FcvvdpCtx *ctx = NULL;
        CHECK(cvvdp_create(W, H, 30, CVVDP_DISPLAY_STANDARD_FHD, threads, NULL, &ctx) == CVVDP_OK);
        FcvvdpResult first;
        CHECK(cvvdp_process_frame(ctx, &ref, &dis, &first) == CVVDP_OK);
        for (int i = 0; i < 4; i++)
            CHECK(cvvdp_process_frame(ctx, &ref, &dis, &actual) == CVVDP_OK);
        CHECK(cvvdp_reset(ctx) == CVVDP_OK);
        CHECK(cvvdp_process_frame(ctx, &ref, &dis, &actual) == CVVDP_OK);
        same_result(actual, first);
        FcvvdpImage wrong = dis;
        wrong.width--;
        CHECK(cvvdp_process_frame(ctx, &ref, &wrong, &actual) == CVVDP_ERROR_DIMENSION_MISMATCH);
        cvvdp_destroy(ctx);
    }

    FcvvdpCtx *ctx = NULL;
    CHECK(cvvdp_create(0, H, 0, CVVDP_DISPLAY_STANDARD_FHD, 1, NULL, &ctx) == CVVDP_ERROR_INVALID_DIMENSIONS);
    CHECK(ctx == NULL);
    CHECK(cvvdp_create(W, H, 0, CVVDP_DISPLAY_STANDARD_FHD, 1, NULL, NULL) == CVVDP_ERROR_NULL_POINTER);
    CHECK(cvvdp_compare_images(NULL, &dis, CVVDP_DISPLAY_STANDARD_FHD, 1, NULL, &actual) == CVVDP_ERROR_NULL_POINTER);
    CHECK(cvvdp_process_frame(NULL, &ref, &dis, &actual) == CVVDP_ERROR_NULL_POINTER);
    CHECK(cvvdp_reset(NULL) == CVVDP_ERROR_NULL_POINTER);
    cvvdp_destroy(NULL);
    for (int model = 0; model < CVVDP_DISPLAY_CUSTOM; model++) {
        FcvvdpDisplayParams params;
        CHECK(cvvdp_get_display_params(model, &params) == CVVDP_OK);
        CHECK(params.max_luminance > 0 && params.resolution_width > 0);
    }
    puts("C API: pixel formats, thread parity, temporal reset, presets and errors passed");
    return 0;
}
