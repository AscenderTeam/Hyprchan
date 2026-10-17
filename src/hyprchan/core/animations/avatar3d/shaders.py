"""Native GLSL implementation of the MToon lit/shade ramp, rim and outline passes.

Reference: VRMC_materials_mtoon-1.0 (VRM Consortium). Portrait-specific hair,
blush and cloth treatments are layered onto that lighting model.
"""

VERTEX = '''#version 330 core
layout(location=0) in vec3 position;
layout(location=1) in vec3 normal;
layout(location=2) in vec2 uv;
layout(location=3) in vec4 joints;
layout(location=4) in vec4 weights;
uniform mat4 bones[160];
uniform mat4 viewProjection;
uniform sampler2D outlineMask;
uniform int kind;
uniform int outlinePass;
uniform float outlineWidth;
out vec3 worldPosition;
out vec3 worldNormal;
out vec2 texCoord;
out vec3 bindPosition;
void main() {
  mat4 skin = weights.x*bones[int(joints.x)] + weights.y*bones[int(joints.y)]
            + weights.z*bones[int(joints.z)] + weights.w*bones[int(joints.w)];
  vec4 p = skin*vec4(position,1.0);
  if(kind==1 && position.z>-.015 && p.y<1.34 && p.y>.98 && abs(p.x)<.19) {
    float front=.016+.155*sqrt(max(0.0,1.0-p.x*p.x/(.19*.19)));
    p.z+=max(0.0,front-p.z)*.9*(1.0-smoothstep(1.26,1.34,p.y));
  }
  worldPosition=p.xyz;
  worldNormal=normalize(mat3(skin)*normal);
  texCoord=uv;
  bindPosition=position;
  if(outlinePass==1) p.xyz+=worldNormal*outlineWidth*texture(outlineMask,uv).g;
  gl_Position=viewProjection*p;
  // Keep the inverted hull behind the surface. This is not a screen filter:
  // the outline follows the skinned, morphed mesh and the face's authored mask.
  if(outlinePass==1) gl_Position.z+=.00005;
}
'''

FRAGMENT = '''#version 330 core
in vec3 worldPosition;
in vec3 worldNormal;
in vec2 texCoord;
in vec3 bindPosition;
uniform sampler2D colorTexture;
uniform sampler2D shadowTexture;
uniform mat4 lightProjection;
uniform int shadowPass;
uniform vec4 baseColor;
uniform int kind;
uniform int outlinePass;
uniform vec3 outlineColor;
uniform vec3 shadeColor;
uniform vec3 rimColor;
uniform float rimPower;
uniform float shadingShift;
uniform float shadingToony;
uniform vec3 viewDirection;
uniform float blush;
uniform float alphaCutoff;
out vec4 color;
vec3 linear(vec3 c) {
  return mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));
}
vec3 srgb(vec3 c) {
  c=max(c,vec3(0));
  return mix(c*12.92,1.055*pow(c,vec3(1.0/2.4))-.055,step(vec3(.0031308),c));
}
void main() {
  vec4 tex=texture(colorTexture,texCoord)*baseColor;
  if(tex.a<alphaCutoff) discard;
  if(shadowPass==1) { color=vec4(1); return; }
  if(outlinePass==1) { color=vec4(srgb(outlineColor),tex.a); return; }
  vec3 paint=srgb(tex.rgb);
  float lum=dot(paint,vec3(.25,.55,.20));
  if(kind==1) {
    // Preserve the original painted strand contrast. Deep blue-green shadows,
    // saturated turquoise mids and mint highlights share a single hue family.
    float value=clamp((lum-.05)*1.85+.12,0.0,1.0);
    paint=mix(vec3(.035,.44,.49),vec3(.22,.95,.84),value);
    paint=mix(paint,vec3(.50,1.0,.90),smoothstep(.65,.95,value)*.65);
  } else if(kind==2) {
    paint=mix(vec3(.012,.06,.11),vec3(.10,.94,.80),smoothstep(.035,.64,lum));
    paint=mix(paint,vec3(.94,1.0,.97),smoothstep(.86,1.0,lum));
  } else if(kind==5) {
    paint=mix(vec3(.025,.20,.25),vec3(.06,.36,.37),lum);
  } else if(kind==6) {
    paint=mix(vec3(.08,.08,.14),vec3(.25,.16,.22),lum);
  }
  vec3 n=normalize(worldNormal);
  if(!gl_FrontFacing) n=-n;
  vec3 light=normalize(vec3(-.65,.55,.65));
  vec3 view=normalize(viewDirection);
  vec3 albedo=linear(paint);
  // MToon 1.0's linear lit/shade ramp. Use derivatives only to antialias
  // its boundary, leaving the intended two-tone shadow intact.
  float ndl=dot(n,light)+shadingShift;
  float edge=max(1.0-shadingToony,fwidth(ndl));
  float ramp=clamp((ndl+edge)/(2.0*edge),0.0,1.0);
  vec3 shadowCoord=(lightProjection*vec4(worldPosition,1)).xyz*.5+.5;
  float visibility=1.0;
  if(all(greaterThan(shadowCoord,vec3(0))) && all(lessThan(shadowCoord,vec3(1)))) {
    visibility=0.0;
    float bias=max(.0012,.0025*(1.0-dot(n,light)));
    vec2 texel=1.0/vec2(textureSize(shadowTexture,0));
    for(int x=-1;x<=1;x++) for(int y=-1;y<=1;y++) {
      float depth=texture(shadowTexture,shadowCoord.xy+vec2(x,y)*texel).r;
      visibility+=shadowCoord.z-bias<=depth?1.0/9.0:0.0;
    }
  }
  // Keep face shadows warm and gentle; let the hood and hair cast distinct
  // blue-lilac shadows onto the white fabric.
  ramp*=mix(1.0,visibility,kind==3?.32:kind==4?1.0:kind==1?.6:0.0);
  vec3 shaded=mix(albedo*shadeColor,albedo,ramp);
  // Equalized ambient fill preserves the illustration's colors on the face.
  shaded*=mix(.96,1.0,clamp(n.y*.5+.5,0.0,1.0));
  float rim=pow(clamp(1.0-dot(n,view),0.0,1.0),max(rimPower,.001));
  shaded+=rimColor*rim;
  if(kind==1) {
    // Broad illustrated hair sheen (view-normal MatCap lobe), not a round
    // plastic specular hotspot. It follows the head when she turns.
    float band=smoothstep(.12,.19,n.y)*(1.0-smoothstep(.34,.42,n.y));
    float facing=smoothstep(.25,.8,dot(n,view));
    shaded+=linear(vec3(.24,.62,.55))*band*facing*.48;
  }
  if(kind==3) {
    float cheek=exp(-pow((abs(bindPosition.x)-.047)/.022,2.0)-pow((bindPosition.y-1.412)/.013,2.0));
    shaded=mix(shaded,linear(vec3(1.0,.43,.52)),cheek*(.10+blush*.43));
  }
  if(kind==2) {
    // Small luminous lower iris, while the pupil and upper lash remain dark.
    shaded+=linear(vec3(.025,.17,.14))*smoothstep(.12,.55,lum);
  }
  color=vec4(srgb(shaded),tex.a);
}
'''
