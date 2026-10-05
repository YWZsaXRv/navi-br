#version 330 core
in  vec2 vUV;
out vec4 fragColor;

uniform float uTime;       // seconds, monotonic
uniform vec3  uAccent;     // accent colour (0..1 per channel)
uniform vec2  uRes;        // viewport size in pixels
uniform int   uPreset;     // 0 = default, 1 = Lottes style
uniform float uDirection;  // 0.0 = bottom→top, 1.0 = top→bottom
uniform bool  uSingleBand; // false = thick, true = thin hotband
uniform bool uHorizontal;  // LTR/RTL

// Cheap screen‑space hash noise
float hash(vec2 p) {
    p  = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

// 1D Gaussian (used in Lottes preset)
float Gaus(float pos, float scale) {
    return exp2(scale * pos * pos);
}

void main() {
    vec2 uv = vUV;
    vec2 c  = uv * 2.0 - 1.0;  // remap [0,1] to centred [-1, 1]

    // Flicker (both presets)
    float drift   = 0.97 + 0.03 * sin(uTime * 1.7);
    float stutter = 1.0  - hash(vec2(floor(uTime * 18.0), 0.3)) * 0.06;
    float flicker = drift * stutter;

    // Darkening layers (scanlines, vignette, barrel edge)
    float scanDark, vigDark, edgeShadow;

    if (uPreset == 0) {
        // Preset A (default, soft CRT)
        // Soft sine‑wave scanlines
        float lineY    = uv.y * uRes.y;
        float softScan = 0.5 + 0.5 * sin(lineY * 3.14159265);
        scanDark       = (1.0 - softScan) * 0.35;

        // Vignette (radial)
        float vd      = dot(c * vec2(0.20, 0.30), c * vec2(0.20, 0.30));
        float vig     = clamp(1.0 - vd, 0.0, 1.0);
        vigDark       = (1.0 - pow(vig, 1.8)) * 0.45;

        // Barrel‑distortion edge shadow
        float barrel     = dot(c, c) * 0.025;
        vec2  warped     = c * (1.0 + barrel);
        vec2  edge       = abs(warped) - 1.0;
        float edgeDist   = length(max(edge, 0.0));
        edgeShadow       = pow(clamp(edgeDist * 6.0, 0.0, 1.0), 0.6) * 0.75;
    } else {
        // Preset B (Lottes‑inspired)
        // Harder scanlines (Gaussian instead of sine)
        float lineY    = uv.y * uRes.y;
        float linePos  = lineY - floor(lineY) - 0.5;  // [-0.5 .. 0.5]
        float scanWeight = Gaus(linePos, -12.0);      // hardScan = -12.0
        scanDark       = (1.0 - scanWeight) * 0.5;

        // Softer vignette, slightly different power
        float vd       = dot(c * vec2(0.45, 0.60), c * vec2(0.45, 0.60));
        float vig      = clamp(1.0 - vd, 0.0, 1.0);
        vigDark        = (1.0 - pow(vig, 1.8)) * 0.45;

        // Weaker barrel edge shadow (Lottes warp is gentler)
        float barrel     = dot(c, c) * 0.05;
        vec2  warped     = c * (1.0 + barrel);
        vec2  edge       = abs(warped) - 1.0;
        float edgeDist   = length(max(edge, 0.0));
        edgeShadow       = pow(clamp(edgeDist * 5.0, 0.0, 1.0), 0.5) * 0.6;
    }

    float darkAlpha = clamp(scanDark + vigDark + edgeShadow, 0.0, 0.92);

    // Bloom / glow (moving hot‑scan band)
    float bloom = 0.0;

    // Scan direction: uDirection = 0.0 → bottom→top, 1.0 → top→bottom
    float scanPos = mod(uTime * 0.22, 1.0);
    if (uDirection > 0.5) scanPos = 1.0 - scanPos;
    float dx;
    if (uHorizontal) {
        dx = abs(uv.x - scanPos);
    } else {
        dx = abs(uv.y - scanPos);
    }

    if (uSingleBand) {
        // Lottes‑style bloom: sharper, single band
        bloom = pow(max(0.0, 1.0 - dx * 30.0), 3.0) * 0.7;
    } else {
        // Default bloom: three concentric bands
        float core  = pow(max(0.0, 1.0 - dx * 22.0), 2.5) * 0.20;
        float mid   = pow(max(0.0, 1.0 - dx *  8.0), 1.8) * 0.20;
        float wide  = pow(max(0.0, 1.0 - dx *  3.0), 1.2) * 0.08;
        bloom = core + mid + wide;
    }

    // Film grain
    float grain = max(0.0, hash(uv + fract(uTime * 0.47)) - 0.25) * 0.20;

    // Phosphor subpixel shimmer / shadow mask
    float shimmer = 0.0;
    vec2 maskPos = uv * uRes / 2.0;          // scale for finer mask
    maskPos.x += maskPos.y * 3.0;
    maskPos.x = fract(maskPos.x / 6.0);
    float maskPattern = 0.5;                 // maskDark
    if (maskPos.x < 0.333) maskPattern = 1.5; // maskLight (R)
    else if (maskPos.x < 0.666) maskPattern = 1.5; // (G)
    else maskPattern = 1.5;                  // (B)
    // We use maskPattern to modulate brightness later
    shimmer = (maskPattern - 0.5) * 0.15;    // gentle influence

    float brightAlpha = clamp((bloom + grain + shimmer) * flicker, 0.0, 0.70);

    // Output // Porter‑Duff "over" baked into a single RGBA
    float outA   = 1.0 - (1.0 - darkAlpha) * (1.0 - brightAlpha);
    vec3  outRGB = (outA > 0.001)
                    ? (uAccent * brightAlpha * (1.0 - darkAlpha)) / outA
                    : vec3(0.0);

    fragColor = vec4(outRGB, outA);
}