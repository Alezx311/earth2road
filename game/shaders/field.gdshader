shader_type spatial;
render_mode cull_back;
uniform vec4 base_color : source_color = vec4(0.69,0.64,0.39,1.0);
void fragment() {
    float phase = (UV.x*0.75+UV.y*0.66)*6.2;
    float antialias = 1.0-smoothstep(0.8,3.14,fwidth(phase));
    float rows = sin(phase)*antialias*0.5+0.5;
    float macro = sin(UV.x*0.027)*sin(UV.y*0.023);
    ALBEDO = base_color.rgb*(0.87+rows*0.15+macro*0.1);
    ROUGHNESS = 0.98;
}
