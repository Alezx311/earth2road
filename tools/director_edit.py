"""Edit a licensed/reference photo and clean engine capture into a silent short.

Recipe paths are relative to its JSON file. Outputs must be fresh. Cropping is a
rectangle only: no perspective warping, mirroring or synthesized imagery.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess


def crop_pixels(size, crop, resolution):
    if len(crop) != 4 or not all(isinstance(v, (int,float)) and math.isfinite(v) for v in crop):
        raise ValueError('crop must be four finite normalized values')
    x,y,w,h = crop
    if min(x,y) < 0 or min(w,h) <= 0 or x+w > 1.000001 or y+h > 1.000001:
        raise ValueError('crop falls outside the source image')
    cw,ch = round(w*size[0]),round(h*size[1])
    if abs(cw/ch-resolution[0]/resolution[1]) > .002:
        raise ValueError('Crop aspect must match output; stretching is not allowed')
    return round(x*size[0]),round(y*size[1]),cw,ch


def capture_crop(size, resolution):
    """Centred crop of an engine frame to the output: same height, never scaled. BeamNG
    captures portrait frames wider than 9:16 (minimum window aspect), see BEAMNG_ASSEMBLY."""
    w, h = size
    if h != resolution[1] or w < resolution[0] or (w-resolution[0]) % 2:
        raise ValueError(f'Capture {size} cannot be cropped to {resolution} without scaling')
    return (w-resolution[0])//2


def edit(recipe_path, output):
    from PIL import Image
    import imageio_ffmpeg
    recipe_path,output = Path(recipe_path).resolve(),Path(output).resolve()
    recipe = json.loads(recipe_path.read_text(encoding='utf-8'))
    photo = recipe_path.parent/recipe['photo']
    frames = recipe_path.parent/recipe['frames']
    if output.exists():
        raise FileExistsError(output)
    sequence = sorted(frames.glob('frame_*.jpg'))
    if len(sequence) != recipe['frame_count'] or any(p.name != f'frame_{i:04d}.jpg' for i,p in enumerate(sequence)):
        raise ValueError('Incomplete capture sequence')
    resolution = recipe['resolution']
    if len(resolution) != 2 or any(type(v) is not int or not 256 <= v <= 3840 or v%2 for v in resolution):
        raise ValueError('Expected even output dimensions from 256 to 3840')
    sizes = set()
    for path in sequence:
        with Image.open(path) as im:
            sizes.add(tuple(im.size))
    if len(sizes) != 1:
        raise ValueError(f'Capture frames differ in size: {sorted(sizes)}')
    capture = list(sizes.pop())
    left = capture_crop(capture, resolution)
    with Image.open(photo) as im:
        x,y,w,h = crop_pixels(im.size,recipe['crop'],resolution)
    hold = float(recipe.get('photo_seconds',2))
    fade = float(recipe.get('transition_seconds',.4))
    if not math.isfinite(hold) or not math.isfinite(fade) or not 0 < fade < hold <= 10:
        raise ValueError('Expected 0 < transition_seconds < photo_seconds <= 10')
    if not recipe.get('credit') or not recipe.get('source_url'):
        raise ValueError('Keep credit and source_url in the recipe and companion post')
    width,height=resolution
    filters=(f'[0:v]crop={w}:{h}:{x}:{y},scale={width}:{height}:flags=lanczos,setsar=1,'
             f'settb=1/30,setpts=N,fps=30,format=yuv420p[p];'
             f'[1:v]crop={resolution[0]}:{resolution[1]}:{left}:0,setsar=1,settb=1/30,setpts=N,fps=30,format=yuv420p[g];'
             f'[p][g]xfade=transition=fade:duration={fade}:offset={hold-fade},format=yuv420p[v]')
    output.parent.mkdir(parents=True,exist_ok=True)
    command=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-filter_complex_threads','2',
             '-loop','1','-framerate','30','-t',str(hold),'-i',str(photo),
             '-framerate','30','-i',str(frames/'frame_%04d.jpg'),'-filter_complex',filters,
             '-map','[v]','-an','-t',str(hold-fade+len(sequence)/30),'-r','30',
             '-c:v','libx264','-threads','4','-preset','medium','-crf','18','-pix_fmt','yuv420p',
             '-movflags','+faststart','-metadata','comment='+recipe['credit']+' | '+recipe['source_url'],str(output)]
    subprocess.run(command,check=True)
    print(output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recipe',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    edit(a.recipe,a.output)
