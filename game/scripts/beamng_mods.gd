extends RefCounted
## The BeamNG.drive mods folder: find it, and add or remove an Earth2Road map ZIP there.
## BeamNG picks new ZIPs up on its next start (or Mods → refresh); a ZIP it has open cannot
## be replaced or removed until BeamNG is closed.

const SETTINGS := "user://settings.cfg"
## Exported ZIP name (tools/export_beamng_gui.py) and the older exporter's name.
const PREFIXES := ["earth2road_", "akadem_drive_"]
const RUN_RE := "^%s-\\d{8}-\\d{6}-[0-9a-f]{8}$"

## The saved folder, else BeamNG's default user folder (0.32+: <user>/current/mods), honouring
## a userFolder set in BeamNG.drive.ini. "" when nothing is found.
static func mods_dir() -> String:
	var settings := ConfigFile.new()
	settings.load(SETTINGS)
	var saved := str(settings.get_value("beamng", "mods_dir", ""))
	if saved != "":
		return saved
	return detect()

static func detect() -> String:
	var local := OS.get_environment("LOCALAPPDATA").replace("\\", "/")
	if local == "":
		return ""
	var user := local + "/BeamNG/BeamNG.drive"
	var ini := local + "/BeamNG/BeamNG.drive.ini"
	if FileAccess.file_exists(ini):
		for line in FileAccess.get_file_as_string(ini).split("\n"):
			var parts := line.split("=", true, 1)
			if parts.size() == 2 and parts[0].strip_edges().to_lower() == "userfolder" and parts[1].strip_edges() != "":
				user = parts[1].strip_edges().replace("\\", "/").trim_suffix("/")
	for candidate in [user + "/current/mods", user + "/mods"]:
		if DirAccess.dir_exists_absolute(candidate):
			return candidate
	return ""

static func set_mods_dir(path: String) -> void:
	var settings := ConfigFile.new()
	settings.load(SETTINGS)
	settings.set_value("beamng", "mods_dir", path)
	settings.save(SETTINGS)

static func zip_name(id: String) -> String:
	return PREFIXES[0] + id + ".zip"

## ZIPs of this map in the mods folder (new and old names).
static func installed(id: String, dir: String = "") -> Array[String]:
	var mods := dir if dir != "" else mods_dir()
	var found: Array[String] = []
	if mods == "":
		return found
	for prefix in PREFIXES:
		var path: String = mods.path_join(prefix + id + ".zip")
		if FileAccess.file_exists(path):
			found.append(path)
	return found

## Copies the export as mods/earth2road_<id>.zip next to BeamNG's other mods (never into a
## subfolder). The old file is replaced only after the copy completed.
static func install(id: String, zip: String) -> Error:
	var mods := mods_dir()
	if mods == "" or not DirAccess.dir_exists_absolute(mods):
		return ERR_FILE_NOT_FOUND
	if not FileAccess.file_exists(zip):
		return ERR_FILE_NOT_FOUND
	var target := mods.path_join(zip_name(id))
	var temp := target + ".part"
	var err := DirAccess.copy_absolute(zip, temp)
	if err != OK:
		DirAccess.remove_absolute(temp)
		return err
	if FileAccess.file_exists(target) and DirAccess.remove_absolute(target) != OK:
		DirAccess.remove_absolute(temp)
		return ERR_FILE_CANT_WRITE   # held open by a running BeamNG
	err = DirAccess.rename_absolute(temp, target)
	if err != OK:
		DirAccess.remove_absolute(temp)
	return err

## Removes every ZIP of this map from the mods folder; stops at a locked file.
static func remove(id: String) -> Error:
	for path in installed(id):
		if DirAccess.remove_absolute(path) != OK:
			return ERR_FILE_CANT_WRITE
	return OK

## The newest validated export of this map in the export folder, or "".
static func latest_export(id: String, exports: String) -> String:
	if exports == "" or not DirAccess.dir_exists_absolute(exports):
		return ""
	var pattern := RegEx.create_from_string(RUN_RE % id)
	var runs := Array(DirAccess.get_directories_at(exports)).filter(func(d: String): return pattern.search(d) != null)
	runs.sort()
	for i in range(runs.size() - 1, -1, -1):
		var run: String = exports.path_join(runs[i])
		var artifact = JSON.parse_string(FileAccess.get_file_as_string(run.path_join("artifact.json")))
		if artifact is Dictionary and str(artifact.get("map", "")) == id:
			var zip := run.path_join(str(artifact.get("zip", zip_name(id))))
			if FileAccess.file_exists(zip):
				return zip
	return ""

## Human message for install/remove errors.
static func error_text(err: Error) -> String:
	if err == ERR_FILE_NOT_FOUND:
		return TranslationServer.translate("BeamNG mods folder not found. Choose it in the map menu.")
	return TranslationServer.translate("Could not change the BeamNG mods folder. Close BeamNG and retry.")
