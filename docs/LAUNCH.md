# Earth2Road presentation package

Goal: invite people to try the experimental generator/game and report concrete map
defects. The public post itself is written and kept outside the repository.

Local delivery folder: `out/earth2road-launch/` (ignored). Exports, media, profiles,
logs and download artifacts do not belong in Git. Engine assets are referenced,
not redistributed. Keep original OSM/terrain attribution with every map.

## Video

1920×1080, 30 fps, H.264 MP4, Ukrainian captions. Engine names stay visible. The
animated Godot build reveal is labelled as a visualization, not elapsed build time.
BeamNG frame-stepped footage is labelled as accelerated. The first cut is silent:
no desktop audio, narration or music is mixed into the captured engine frames.

| Seconds | Content |
|---|---|
| 0–5 | BeamNG driving hook: «А як щодо проїхатися своїм містом?» |
| 5–9 | Actual Earth2Road location picker |
| 9–24 | Kyiv, Lviv, Odesa layer reveal; city captions |
| 24–31 | Godot gameplay with SUMO traffic |
| 31–36 | Actual export UI; cut rather than a false instant-completion claim |
| 36–54 | BeamNG driving in the three maps |
| 54–60 | Earth2Road, ten Ukrainian cities, invitation to test |

Capture each take in its own fresh directory. `tools/capture_timelapses.py` owns its
bridge on port 8798, records engine frames, and stops only its own child process.
Do not overwrite the normal active map or the user's BeamNG profile.

Capture helpers: `capture_beamng.py`, `capture_godot_promo.py`; edit with
`edit_promo.py --input out/earth2road-launch --output out/earth2road-launch/video`.
The edit helper needs the optional local `imageio-ffmpeg` package and Windows Segoe
fonts. These are presentation tooling, not new game runtime requirements.

## Download package

Three independent BeamNG ZIPs, install instructions in Ukrainian, SHA256 checksums,
and exact runtime results/limitations per map. Use a GitHub prerelease for eventual
distribution; the Reddit post and public release are not sent automatically.

Do not describe a map as runtime verified based only on ZIP validation. Check load,
vehicle contact and travel, seams, traffic, materials and signs/signals in BeamNG.
Keep failures visible in the acceptance record and exclude a broken package from
the public download selection until repaired.
