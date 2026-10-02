"""Assemble captured engine frames into the 60-second Ukrainian presentation."""
import argparse
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont


def overlay(path, title, subtitle, engine, end=False, hud=False):
    image = Image.new('RGBA', (1920, 1080))
    draw = ImageDraw.Draw(image)
    fonts = Path('C:/Windows/Fonts')
    regular = lambda size: ImageFont.truetype(str(fonts/'segoeui.ttf'), size)
    bold = lambda size: ImageFont.truetype(str(fonts/'segoeuib.ttf'), size)
    if end:
        draw.rectangle((0, 0, 1920, 1080), fill=(8, 18, 25, 185))
        draw.text((100, 260), 'Earth2Road', font=bold(128), fill='white')
        draw.text((108, 442), title, font=regular(54), fill='white')
        draw.rectangle((108, 540, 620, 548), fill='#61e3b1')
        draw.text((108, 608), subtitle, font=regular(42), fill='#ccded8')
        draw.text((108, 700), 'Спробуйте карту. Поділіться відгуком.', font=bold(42), fill='#61e3b1')
    elif hud:
        # The game draws its own HUD along the top edge: keep that clear and
        # name the engine above the caption instead.
        for y in range(790, 1080):
            alpha = int(220*min(1, (y-790)/170))
            draw.line((0, y, 1920, y), fill=(8, 18, 25, alpha))
        draw.text((98, 846), engine, font=regular(28), fill='#c7eee0')
        draw.rectangle((64, 902, 72, 1018), fill='#61e3b1')
        draw.text((96, 890), title, font=bold(52), fill='white')
        draw.text((98, 966), subtitle, font=regular(31), fill='#d2dfdc')
    else:
        draw.rounded_rectangle((48, 38, 335, 104), radius=13, fill=(8, 18, 25, 225))
        draw.text((70, 46), 'Earth2Road', font=bold(38), fill='white')
        bbox = draw.textbbox((0, 0), engine, font=regular(28))
        width = bbox[2]+44
        draw.rounded_rectangle((1872-width, 38, 1872, 98), radius=13, fill=(8, 18, 25, 225))
        draw.text((1894-width, 48), engine, font=regular(28), fill='#c7eee0')
        for y in range(790, 1080):
            alpha = int(220*min(1, (y-790)/170))
            draw.line((0, y, 1920, y), fill=(8, 18, 25, alpha))
        draw.rectangle((64, 902, 72, 1018), fill='#61e3b1')
        draw.text((96, 890), title, font=bold(52), fill='white')
        draw.text((98, 966), subtitle, font=regular(31), fill='#d2dfdc')
    draw.text((64, 1042), '© OpenStreetMap contributors · ODbL   |   Terrain: Mapzen',
              font=regular(18), fill='#d0dad7')
    image.save(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    source, out = args.input.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    beam = lambda mid: source/'beamng'/mid/'user/current/screenshots/promo'
    godot = source/'godot-promo'
    takes = source/'timelapses'
    # folder, input fps, first frame, seconds, title, subheading, engine label, end card
    # ('hud' marks takes that already show the game's own top-edge HUD)
    shots = [
        (beam('kyiv_maidan'),30,30,5,'А як щодо проїхатися своїм містом?',
         'Реальна локація → згенерована карта → гра','BeamNG.drive · прискорено',False),
        (godot/'picker',30,0,4,'Обери місце на карті',
         'Локація, розмір ділянки — і генерація','Earth2Road · інтерфейс',False),
        (takes/'kyiv_maidan',60,0,5,'Київ',
         'Рельєф → дороги → будинки → трафік','Godot · візуалізація генерації',False),
        (takes/'lviv_center',60,0,5,'Львів',
         'Та сама система, інша дорожня мережа','Godot · візуалізація генерації',False),
        (takes/'odesa',60,0,5,'Одеса',
         'Локації вже згенеровані у 10 містах України','Godot · візуалізація генерації',False),
        (godot/'godot-drive',30,0,7,'Грай в Earth2Road',
         'Власна гра на Godot · симуляція трафіку SUMO','Godot · геймплей','hud'),
        (godot/'export',30,0,5,'Або експортуй у BeamNG.drive',
         'Обери карту → збережи ZIP → встанови мод','Earth2Road · інтерфейс',False),
        (beam('kyiv_maidan'),30,60,6,'Київ у BeamNG.drive',
         'Дороги, колізії та AI-трафік','BeamNG.drive · прискорено',False),
        (beam('lviv_center'),30,60,6,'Львів у BeamNG.drive',
         'Той самий генератор · інший рушій','BeamNG.drive · прискорено',False),
        (beam('odesa'),30,60,6,'Одеса у BeamNG.drive',
         'Готові ZIP для першого тесту','BeamNG.drive · прискорено',False),
        (takes/'kyiv_maidan',15,540,6,'З реальної мапи — у гру',
         'Відкритий код · експериментальна beta · посилання в дописі','',True),
    ]
    clips = []
    for i, (folder, fps, start, duration, title, subtitle, engine, end) in enumerate(shots):
        last = start+fps*duration-1
        if not (folder/f'frame_{last:04d}.jpg').exists():
            raise FileNotFoundError(f'Missing complete take: {folder} frame {last}')
        art = out/f'overlay-{i:02d}.png'
        clip = out/f'clip-{i:02d}.mp4'
        overlay(art, title, subtitle, engine, end is True, end == 'hud')
        cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-threads', '2',
               '-framerate', str(fps), '-start_number', str(start), '-i', str(folder/'frame_%04d.jpg'),
               '-loop', '1', '-i', str(art), '-filter_complex_threads', '2',
               '-filter_complex', '[0:v]fps=30,scale=1920:1080,setsar=1[v];[v][1:v]overlay=0:0:shortest=1,format=yuv420p',
               '-t', str(duration), '-an', '-c:v', 'libx264', '-threads', '2', '-preset', 'medium',
               '-crf', '19', '-movflags', '+faststart', str(clip)]
        subprocess.run(cmd, check=True)
        clips.append(clip)
        print('EDIT_CLIP', i+1, '/', len(shots), flush=True)
    listing = out/'clips.txt'
    listing.write_text(''.join("file '"+p.name+"'\n" for p in clips), encoding='utf-8')
    final = out/'Earth2Road-ukraine-dev-60s.mp4'
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
                    '-i', str(listing), '-c', 'copy', '-movflags', '+faststart', str(final)], check=True)
    print('VIDEO_READY', final, flush=True)


if __name__ == '__main__':
    main()
