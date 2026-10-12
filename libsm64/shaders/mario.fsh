#version 130

uniform sampler2D p3d_Texture0;

in vec2 texcoord;
in vec4 vcolor;
in vec3 vnormal;

out vec4 p3d_FragColor;

void main() {
  // libsm64 UVs are top-down; the atlas loaded through PNMImage is bottom-up
  vec4 tex = texture(p3d_Texture0, vec2(texcoord.x, -texcoord.y));
  vec3 base = mix(vcolor.rgb, tex.rgb, tex.a);

  // simple fixed key light in SM64 model space (Y up)
  vec3 lightDir = normalize(vec3(0.3, 1.0, 0.5));
  float diffuse = 0.65 + 0.35 * max(dot(normalize(vnormal), lightDir), 0.0);

  p3d_FragColor = vec4(base * diffuse, 1.0);
}
