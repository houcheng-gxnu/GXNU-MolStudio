"""
GLSL Shader Module — Ported from IboView's shader pipeline.
Provides vertex/fragment shaders for:
  - Three-directional Phong lighting (Mayavi light setup)
  - Depth peeling for correct transparency ordering
  - Depth fade for depth perception
  - FXAA-ready supersampling support
"""

# ── Vertex Shader ──────────────────────────────────────────
# Ported from IboView shader/vertex5.glsl
VERTEX_SHADER = """
#version 330 core

layout(location = 0) in vec3 in_Position;
layout(location = 1) in vec3 in_Normal;
layout(location = 2) in vec4 in_Color;

out vec3 v_Normal;
out vec4 v_Color;

uniform mat4 u_ModelView;
uniform mat3 u_NormalMatrix;
uniform mat4 u_Projection;

void main() {
    gl_Position = u_Projection * (u_ModelView * vec4(in_Position, 1.0));
    v_Normal = u_NormalMatrix * in_Normal;
    v_Color = in_Color;
}
"""

# ── Common Lighting Functions ──────────────────────────────
# Ported from IboView shader/pixel_common.glsl
# Three-directional light (Mayavi standard setup)
LIGHTING_COMMON = """
// ── Shader Uniforms ──
uniform float ShaderReg0;  // diffuse exponent (pow base)
uniform float ShaderReg1;  // diffuse intensity
uniform float ShaderReg2;  // specular intensity
uniform float ShaderReg3;  // specular balance (mix between two exponents)
uniform float FadeBias;    // depth fade bias
uniform float FadeWidth;   // depth fade width
uniform vec4 DiffuseColor; // surface diffuse color

// ── Three-directional light (Mayavi setup) ──
const vec3 LightDir0 = vec3( 0.50000000,  0.50000000, 0.70710678);
const vec3 LightDir1 = vec3(-0.43301270, -0.25000000, 0.86602540);
const vec3 LightDir2 = vec3( 0.43301270, -0.25000000, 0.86602540);

vec4 calc_light(vec3 N, vec3 L, float intensity) {
    float cosA = clamp(dot(N, L), 0.0, 1.0);
    vec4 cDiffuse = ShaderReg1 * pow(cosA, ShaderReg0) * DiffuseColor;
    // IboView double-exponential specular:
    // ShaderReg3 controls balance between sharp (16) and very sharp (64) highlights
    vec4 SpecularColor = vec4(1.0, 1.0, 1.0, 0.0);
    vec4 cSpecular = ShaderReg2 *
        (ShaderReg3 * pow(cosA, 16.0) + 1.2 * pow(cosA, 64.0)) *
        SpecularColor;
    vec4 cOut = v_Color * cDiffuse + cSpecular;
    return intensity * cOut;
}

vec3 fade_base_color(vec3 color) {
    float rz = clamp(FadeWidth * (gl_FragCoord.z - 0.5) + FadeBias, 0.0, 1.0);
    return mix(color, vec3(1.0, 1.0, 1.0), rz);
}

vec4 calc_base_color_with_normal(vec3 N) {
    vec3 vNorm = normalize(N);
    vec4 color = calc_light(vNorm, LightDir0, 1.0) +
                 calc_light(vNorm, LightDir1, 0.6) +
                 calc_light(vNorm, LightDir2, 0.5);
    // edge darkening based on z-component of normal
    color.rgb /= clamp(abs(vNorm.z), 0.1, 1.0);
    color.rgb = fade_base_color(color.rgb);
    return color;
}

vec4 calc_base_color(vec3 in_Normal, bool flip_sides) {
    if (!flip_sides) {
        return calc_base_color_with_normal(in_Normal);
    } else {
        vec3 N = in_Normal;
        if (!gl_FrontFacing)
            N = -N;
        return calc_base_color_with_normal(N);
    }
}
"""

# ── Opaque Fragment Shader ─────────────────────────────────
# Ported from IboView shader/pixel5.glsl
# Used for opaque objects (atoms, bonds) and as the base lighting pass
FRAGMENT_OPAQUE = """
#version 330 core

in vec3 v_Normal;
in vec4 v_Color;

layout(location = 0) out vec4 out_Color;

""" + LIGHTING_COMMON + """

void main() {
    out_Color = calc_base_color(v_Normal, false);
    out_Color.a = 1.0;
}
"""

# ── Orbital Depth Peeling Fragment Shader ──────────────────
# Ported from IboView shader/pixel5_orb_dp.glsl
# Only renders fragments that are in front of the previous depth layer
FRAGMENT_ORBITAL_DP = """
#version 330 core

in vec3 v_Normal;
in vec4 v_Color;

layout(location = 0) out vec4 out_Color;

uniform sampler2D DepthPrev;  // depth texture from previous peel layer

""" + LIGHTING_COMMON + """

void main() {
    ivec2 coord = ivec2(gl_FragCoord.xy);
    float prevDepth = texelFetch(DepthPrev, coord, 0).r;

    // Only render if this fragment is in front of the previous layer
    if (gl_FragCoord.z < prevDepth || prevDepth <= 0.0) {
        out_Color = calc_base_color(v_Normal, true);
    } else {
        discard;
    }
}
"""

# ── Depth Peeling Composite Shader ─────────────────────────
# Ported from IboView shader/pixel5_combine_dp.glsl
# Composites the current layer color into the accumulation buffer
FRAGMENT_COMPOSITE = """
#version 330 core

uniform sampler2D LayerColor;  // RGBA output of current peel layer

layout(location = 0) out vec4 out_Color;

void main() {
    ivec2 coord = ivec2(gl_FragCoord.xy);
    vec4 layer = texelFetch(LayerColor, coord, 0);

    if (abs(layer.a) < 1e-2) {
        discard;
    } else {
        out_Color = layer;
    }
}
"""

# ── Simple Pass-Through Vertex Shader (fullscreen quad) ────
# Used for composite/depth-copy passes
FULLSCREEN_VERTEX = """
#version 330 core

layout(location = 0) in vec2 in_Position;
layout(location = 1) in vec2 in_TexCoord;

out vec2 v_TexCoord;

void main() {
    gl_Position = vec4(in_Position, 0.0, 1.0);
    v_TexCoord = in_TexCoord;
}
"""

# ── Depth Copy Fragment Shader ─────────────────────────────
# Copies depth buffer to a color texture for the next peel pass
FRAGMENT_DEPTH_COPY = """
#version 330 core

in vec2 v_TexCoord;

uniform sampler2D DepthTex;

layout(location = 0) out vec4 out_Color;

void main() {
    float d = texture(DepthTex, v_TexCoord).r;
    out_Color = vec4(d, 0.0, 0.0, 1.0);
}
"""

# ── Background Fragment Shader ─────────────────────────────
FRAGMENT_BACKGROUND = """
#version 330 core

layout(location = 0) out vec4 out_Color;

uniform vec4 u_BgColor;

void main() {
    out_Color = u_BgColor;
}
"""

# ── Atom Sphere Fragment Shader ────────────────────────────
# Uses lighting but with a separate diffuse color for atoms
FRAGMENT_ATOM = """
#version 330 core

in vec3 v_Normal;
in vec4 v_Color;

layout(location = 0) out vec4 out_Color;

""" + LIGHTING_COMMON + """

void main() {
    out_Color = calc_base_color(v_Normal, false);
    // Keep alpha from vertex color for transparent atoms
    out_Color.a = v_Color.a;
}
"""

# ── Shader Register Defaults ───────────────────────────────
# These map style surface_mat parameters to IboView shader registers.
# surface_mat format: [ambient, diffuse, specular, shininess, mirror, opacity,
#                      outline, outlinewidth, transmode]
#
# Mapping to shader uniforms:
#   ShaderReg0 = diffuse exponent (1.0 .. 3.0, from shininess)
#   ShaderReg1 = diffuse intensity (from surface_mat[1] = diffuse)
#   ShaderReg2 = specular intensity (from surface_mat[2] = specular)
#   ShaderReg3 = specular balance (from shininess, 0.0 .. 1.0)
#   FadeBias = 0.2 (default, as in IboView)
#   FadeWidth = 6.0 (default, as in IboView)


def style_to_shader_params(surface_mat):
    """Convert a surface_mat list to IboView shader uniform values.

    surface_mat: [ambient, diffuse, specular, shininess, mirror, opacity,
                  outline, outlinewidth, transmode]

    Returns dict of shader uniform values.
    """
    ambient, diffuse, specular, shininess, mirror, opacity = surface_mat[:6]

    # Map shininess (0..1) to ShaderReg0 (diffuse exponent: 1..4)
    ShaderReg0 = 1.0 + 3.0 * shininess

    # Map diffuse to ShaderReg1
    ShaderReg1 = diffuse

    # Map specular to ShaderReg2 (scale to IboView range)
    ShaderReg2 = specular * 1.0

    # Map shininess to ShaderReg3 (specular balance: 0..1)
    ShaderReg3 = shininess

    return {
        'ShaderReg0': ShaderReg0,
        'ShaderReg1': ShaderReg1,
        'ShaderReg2': ShaderReg2,
        'ShaderReg3': ShaderReg3,
        'FadeBias': 0.2,
        'FadeWidth': 6.0,
        'opacity': opacity,
    }


def parse_style_rgb(style_color):
    """Parse a style color entry (from STYLES dict) to (r, g, b) tuple.

    Format: [ColorID, r, g, b]  or  [ColorID, None, None, None]
    """
    if len(style_color) >= 4:
        r, g, b = style_color[1], style_color[2], style_color[3]
        if r is not None and g is not None and b is not None:
            return (r, g, b)
    return None
