# Earth2Road scope

One standalone repository contains the Python world generator, Godot driving game,
SUMO traffic bridge and BeamNG.drive exporter. The bundled offline fixture is synthetic.

Publication gate: independent installation, complete unittest discovery, wheel/sdist,
offline world build and validation, both exporters, Godot script/runtime checks,
source hygiene and preserved third-party attribution. Record results in VALIDATION.

Real-map acceptance is separate: geometry, spawned vehicle contact, traversable seams,
signals, traffic and performance must be checked for each rebuilt map and engine.
Large historical maps are not included in Git or certified by a passing tiny fixture.
