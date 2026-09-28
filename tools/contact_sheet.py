#!/usr/bin/env python3
"""Tile logs/shots/*.png (or a given folder) into one JPEG for quick visual review."""
import glob
import sys
from PIL import Image

src = sys.argv[1] if len(sys.argv) > 1 else 'logs/shots'
out = sys.argv[2] if len(sys.argv) > 2 else src.rstrip('/')+'_sheet.jpg'
files = sorted(glob.glob(src+'/*.png'))
sheet = Image.new('RGB', (1920, 540*((len(files)+1)//2)))
for i, f in enumerate(files):
    sheet.paste(Image.open(f).convert('RGB').resize((960, 540)), ((i % 2)*960, (i//2)*540))
sheet.save(out, quality=85)
print(out, [f.split('/')[-1] for f in files])
