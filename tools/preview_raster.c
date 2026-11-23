#include <math.h>
#include <stdint.h>

void paint(uint8_t *pixels, float *depth, int w, int h, const float *tris,
           const float *light, int count, const uint8_t *texture, int tw, int th) {
    for (int n = 0; n < count; ++n) {
        const float *a = tris + n * 15, *b = a + 5, *c = b + 5;
        float ex = b[0] - a[0], ey = b[1] - a[1], fx = c[0] - a[0], fy = c[1] - a[1];
        float det = ex * fy - ey * fx;
        if (fabsf(det) < 0.0001f) continue;
        int x0 = (int) fmaxf(0, floorf(fminf(a[0], fminf(b[0], c[0]))));
        int x1 = (int) fminf(w-1, ceilf(fmaxf(a[0], fmaxf(b[0], c[0]))));
        int y0 = (int) fmaxf(0, floorf(fminf(a[1], fminf(b[1], c[1]))));
        int y1 = (int) fminf(h-1, ceilf(fmaxf(a[1], fmaxf(b[1], c[1]))));
        float shade = light[n];
        for (int y = y0; y <= y1; ++y) {
            for (int x = x0; x <= x1; ++x) {
                float dx = x + .5f - a[0], dy = y + .5f - a[1];
                float u = (dx * fy - dy * fx) / det;
                float v = (ex * dy - ey * dx) / det, s = 1 - u - v;
                if (u < -0.0001f || v < -0.0001f || s < -0.0001f) continue;
                float z = s * a[2] + u * b[2] + v * c[2];
                int loc = y * w + x;
                if (z <= depth[loc]) continue;
                depth[loc] = z;
                float tx = s * a[3] + u * b[3] + v * c[3];
                float ty = s * a[4] + u * b[4] + v * c[4];
                int i = (int) fmaxf(0, fminf(tw-1, tx * tw));
                int j = (int) fmaxf(0, fminf(th-1, (1-ty) * th));
                const uint8_t *rgb = texture + 3 * (j * tw + i);
                uint8_t *p = pixels + 4 * loc;
                p[0] = (uint8_t) fminf(255, rgb[0] * shade * 1.035f + 4);
                p[1] = (uint8_t) fminf(255, rgb[1] * shade + 5);
                p[2] = (uint8_t) fminf(255, rgb[2] * shade * .97f + 9);
                p[3] = 255;
            }
        }
    }
}
