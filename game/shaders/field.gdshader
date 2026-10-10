shader_type spatial;
render_mode cull_back;
global uniform int facade_style;   // 2 = synthwave: dark teal with a grid along the rows; 3 = NES rows
uniform vec4 base_color : source_color = vec4(0.69,0.64,0.39,1.0);
void fragment() {
    float phase = (UV.x*0.75+UV.y*0.66)*6.2;
    float antialias = 1.0-smoothstep(0.8,3.14,fwidth(phase));
    float rows = sin(phase)*antialias*0.5+0.5;
    float macro = sin(UV.x*0.027)*sin(UV.y*0.023);
    ALBEDO = base_color.rgb*(0.87+rows*0.15+macro*0.1);
    ROUGHNESS = 0.98;
    if (facade_style == 2) {
        float glow = (1.0 - smoothstep(0.0, 0.12 + fwidth(phase), abs(sin(phase * 0.25)))) * (1.0 - smoothstep(0.6, 2.5, fwidth(phase)));
        ALBEDO = vec3(.01, .03, .04);
        EMISSION = vec3(.08, .9, 1.0) * glow * 0.9;
        ROUGHNESS = 0.5;
    }
    if (facade_style == 3) {
        // NES: rows two pixels of crop, one of soil, in palette colours.
        float row = mod(floor(phase * 0.6), 3.0);
        ALBEDO = row < 0.5 ? vec3(.314, .188, 0.) : (base_color.g > base_color.r ? vec3(0., .659, 0.) : vec3(.973, .722, 0.));
        ROUGHNESS = 1.0;
    }
}
