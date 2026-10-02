extends RefCounted
## UI language. English strings are the translation keys (tr("…") reads as English in the
## code); Ukrainian is registered at runtime from the table below. The project runs from
## source without Godot's import step, so an imported CSV translation would never load.
## The choice is kept in user://settings.cfg; English is the default.

const SETTINGS := "user://settings.cfg"
const LOCALES := ["en", "uk"]

const UK := {
	"Export to BeamNG…": "Експорт у BeamNG…",
	"EXPORT TO BEAMNG": "ЕКСПОРТ У BEAMNG",
	"Save ZIP to": "Папка для ZIP",
	"Browse…": "Обрати…",
	"Select Current Folder": "Обрати цю папку",
	"Path:": "Шлях:",
	"Favorites:": "Обране:",
	"Recent:": "Нещодавні:",
	"Directories & Files:": "Папки й файли:",
	"Create Folder": "Створити папку",
	"Each export gets a new folder. Previous ZIPs are kept.": "Кожен експорт створює нову папку. Попередні ZIP зберігаються.",
	"Optimization": "Оптимізація",
	"A+B+C: all optimizations (large maps)": "A+B+C: усі оптимізації (великі карти)",
	"Smallest level and fastest first load: compact files, light kerbs and native terrain ground. Recommended for maps of several kilometres.": "Найменший рівень і найшвидше перше завантаження: компактні файли, легкі бордюри й нативна земля terrain. Рекомендовано для карт у кілька кілометрів.",
	"Original": "Оригінал",
	"Reference export with full kerb detail and mesh ground. Largest files; large maps may not load.": "Еталонний експорт із повною деталізацією бордюрів і землею з мешів. Найбільші файли; великі карти можуть не завантажитися.",
	"A: compact files": "A: компактні файли",
	"Same geometry, 1 mm coordinates and smoothed shading: about 70% smaller model files.": "Та сама геометрія, координати з точністю 1 мм і згладжене освітлення: файли моделей приблизно на 70% менші.",
	"B: light kerbs": "B: легкі бордюри",
	"Kerbs without the small bevel and with simpler outlines: about 88% fewer sidewalk triangles.": "Бордюри без дрібної фаски та зі спрощеним контуром: приблизно на 88% менше трикутників тротуарів.",
	"C: terrain ground": "C: земля як terrain",
	"Ground becomes a native BeamNG terrain under the roads instead of meshes; grass extends past the map edge.": "Земля стає нативним terrain BeamNG під дорогами замість мешів; трава тягнеться за межі карти.",
	"Ready to export": "Готово до експорту",
	"Export ZIP": "Експортувати ZIP",
	"Export again": "Експортувати знову",
	"Open folder": "Відкрити папку",
	"Copy ZIP path": "Копіювати шлях до ZIP",
	"Copy the ZIP into your BeamNG.drive user folder's mods folder to install it.": "Для встановлення скопіюйте ZIP у папку mods у папці користувача BeamNG.drive.",
	"Checking map data…": "Перевіряємо дані карти…",
	"Exporting sidewalks…": "Експортуємо тротуари…",
	"Exporting buildings…": "Експортуємо будівлі…",
	"Exporting vegetation and signs…": "Експортуємо рослинність і знаки…",
	"Exporting roads and scenery…": "Експортуємо дороги й оточення…",
	"Checking the level…": "Перевіряємо рівень…",
	"Creating ZIP…": "Створюємо ZIP…",
	"Checking ZIP…": "Перевіряємо ZIP…",
	"Elapsed: %d s": "Минуло: %d с",
	"ZIP ready: %s": "ZIP готовий: %s",
	"Export cancelled": "Експорт скасовано",
	"Choose an absolute output folder path.": "Оберіть повний шлях до папки збереження.",
	"Python environment missing. Run Earth2Road setup and retry.": "Середовище Python відсутнє. Запустіть налаштування Earth2Road та повторіть.",
	"Could not write export logs. Check folder permissions.": "Не вдалося записати журнал експорту. Перевірте права доступу до папки.",
	"Could not start the exporter. Check technical details.": "Не вдалося запустити експорт. Перегляньте технічні подробиці.",
	"Export failed. Check technical details and retry.": "Експорт не вдався. Перегляньте технічні подробиці та повторіть.",
	"Map data is missing. Generate the map again before exporting.": "Дані карти відсутні. Згенеруйте карту знову перед експортом.",
	"Map files do not match. Generate the map again before exporting.": "Файли карти не узгоджені. Згенеруйте карту знову перед експортом.",
	"Cannot write to this folder. Choose another folder and retry.": "Не вдалося записати в цю папку. Оберіть іншу папку та повторіть.",
	"Maps · M": "Карти · M",
	"Pause · P": "Пауза · P",
	"Camera · C": "Камера · C",
	"Spectator · F": "Огляд · F",
	"Traffic · T": "Трафік · T",
	"Help · F1": "Довідка · F1",
	"LOCAL ROADS   /   N ↑": "ДОРОГИ ПОРУЧ   /   Пн ↑",
	"%d cars · %d FPS · %s": "%d авто · %d FPS · %s",
	"Close · Esc": "Закрити · Esc",
	"Choose your next drive": "Оберіть місце для наступної поїздки",
	"Search installed maps…": "Пошук серед встановлених карт…",
	"No maps found. Try another search or create a map.": "Карт не знайдено. Змініть пошук або створіть нову карту.",
	"PAUSED": "ПАУЗА",
	"Take your time. Your drive will wait.": "Можна перепочити. Поїздка зачекає.",
	"Resume driving · P": "Продовжити поїздку · P",
	"Traffic control": "Керування трафіком",
	"Time speed applies in spectator mode": "Швидкість часу діє в режимі спостерігача",
	"Traffic demand is synthetic": "Попит трафіку змодельований, не виміряний",
	"Select a tool, then click a road": "Оберіть інструмент і клацніть по дорозі",
	"%s · Click a road · ESC — cancel": "%s · Клік по дорозі · ESC — скасувати",
	"Choose a place. Build a drive.": "Оберіть місце. Створіть поїздку.",
	"1 / LOCATION": "1 / МІСЦЕ",
	"2 / AREA & DETAILS": "2 / ОБЛАСТЬ І ПАРАМЕТРИ",
	"3 / BUILD": "3 / ПОБУДОВА",
	"Find a place": "Знайти місце",
	"Search": "Знайти",
	"Technical details": "Технічні подробиці",
	"Select an area, then Generate": "Оберіть область і натисніть «Згенерувати»",
	"Server busy. Trying another source…": "Сервер зайнятий. Пробуємо інше джерело…",
	"Could not build the map. Check your connection and retry.": "Не вдалося створити карту. Перевірте з’єднання та повторіть.",
	"Building roads and scenery…": "Будуємо дороги й оточення…",
	"Preparing the map to drive…": "Готуємо карту до поїздки…",
	"Downloading map data…": "Завантажуємо дані карти…",
	"Recording data sources…": "Записуємо джерела даних…",
	"Installing the map…": "Встановлюємо карту…",
	"Working…": "Триває робота…",
	"Reading the map data…": "Читаємо дані карти…",
	"Shaping the terrain…": "Формуємо рельєф…",
	"Building the road network…": "Будуємо дорожню мережу…",
	"Placing buildings…": "Розставляємо будівлі…",
	"Placing trees…": "Висаджуємо дерева…",
	"Placing road signs…": "Розставляємо дорожні знаки…",
	"Packing map tiles…": "Пакуємо фрагменти карти…",
	"Checking road surfaces…": "Перевіряємо покриття доріг…",
	"Retry": "Повторити",
	"Could not build this area. Move it or make it larger, then retry.": "Не вдалося побудувати цю область. Посуньте або збільште її й повторіть.",
	"Cancelling…": "Скасування…",
	"Generation cancelled": "Генерацію скасовано",
	# HUD status
	"LOADING": "ЗАВАНТАЖЕННЯ",
	"PAUSED · P — resume": "ПАУЗА · P — продовжити",
	"NO TRAFFIC": "БЕЗ ТРАФІКУ",
	"CONNECTING TO TRAFFIC · F5 — retry": "З’ЄДНАННЯ З ТРАФІКОМ · F5 — повторити",
	"NO TRAFFIC BRIDGE · run start.ps1 · F5": "НЕМАЄ МОСТА ТРАФІКУ · start.ps1 · F5",
	"LOADING TRAFFIC FOR THIS MAP…": "ЗАВАНТАЖЕННЯ ТРАФІКУ ДЛЯ КАРТИ…",
	"FREE DRIVE": "ВІЛЬНА ПОЇЗДКА",
	"SPECTATOR · TIME STOPPED": "СПОСТЕРЕЖЕННЯ · ЧАС ЗУПИНЕНО",
	"SPECTATOR · ×%d (actual ×%.1f)": "СПОСТЕРЕЖЕННЯ · ×%d (факт. ×%.1f)",
	"SPECTATOR · ×%d": "СПОСТЕРЕЖЕННЯ · ×%d",
	"%d cars  ·  %d FPS  ·  %s\n%s · SUMO %.0f ms": "%d авто  ·  %d FPS  ·  %s\n%s · SUMO %.0f мс",
	"camera %.0f m": "камера %.0f м",
	"km/h": "км/год",
	"TRAFFIC DENSITY · %d cars  (−/+)": "ЩІЛЬНІСТЬ РУХУ · %d авто  (−/+)",
	"\n× frame rate and SUMO step will drop": "\n× кадр і крок SUMO просядуть",
	"\n× the network cannot hold that many": "\n× мережа не вміщає стільки",
	# Help (F1)
	"CONTROLS · F1": "КЕРУВАННЯ · F1",
	"DRIVING": "ВОДІННЯ",
	"WASD or arrows — throttle, brake, steer (S when stopped — reverse) · SPACE — handbrake\nC — camera · RMB + mouse — look around · wheel — camera distance · V — car model · R — back to start":
		"WASD або стрілки — газ, гальмо, кермо (S на місці — задній хід) · SPACE — ручник\nC — камера · ПКМ + миша — огляд · колесо — відстань камери · V — модель авто · R — на старт",
	"SPECTATOR": "СПОСТЕРІГАЧ",
	"F — free camera over the city · WASD move · wheel or Q/E height\nRMB + mouse — turn and tilt · MMB — pan · Z/X — rotate · SHIFT — faster":
		"F — вільна камера над містом · WASD рух · колесо або Q/E висота\nПКМ + миша — поворот і нахил · СКМ — панорама · Z/X — поворот · SHIFT — швидше",
	"TIME AND TRAFFIC": "ЧАС І ТРАФІК",
	"1–6 or [ ] — time speed ×0 … ×16 · −/+ or slider — traffic density\nP or ESC — pause · F5 — reconnect traffic · F12 — screenshot":
		"1–6 або [ ] — швидкість часу ×0 … ×16 · −/+ або повзунок — щільність руху\nP або ESC — пауза · F5 — перепідключити трафік · F12 — знімок",
	"ROAD SITUATIONS": "ДОРОЖНІ СИТУАЦІЇ",
	"T — panel: accident, lane closure, roadworks, jam, speed limit\nPick a situation and click a road · a click without one shows what is there and unlocks the traffic light":
		"T — панель: ДТП, перекриття смуги, ремонт, затор, обмеження швидкості\nОберіть подію й клацніть по дорозі · клік без події показує, що там, і відкриває світлофор",
	"M — map menu · L — language (English / Українська)": "M — вибір карти · L — мова (English / Українська)",
	"Heights, facades, signs and signal phases are approximate or derived, not surveyed":
		"Висоти, фасади, знаки й фази світлофорів — приблизні або виведені з даних, не заміряні",
	# Traffic panel (T)
	"TRAFFIC CONTROL · T": "КЕРУВАННЯ ТРАФІКОМ · T",
	"SITUATION": "ПОДІЯ",
	"Accident": "ДТП",
	"Stalled car": "Несправне авто",
	"Lane closed": "Закрита смуга",
	"Roadworks": "Ремонт дороги",
	"Traffic jam": "Затор",
	"Speed limit": "Обмеження",
	"30 s": "30 с",
	"1 min": "1 хв",
	"5 min": "5 хв",
	"until cancelled": "до скасування",
	"Next phase": "Наступна фаза",
	"All red": "Усе червоне",
	"Flashing amber": "Жовте блимання",
	"Turn off": "Вимкнути",
	"Restore": "Відновити",
	"Duration": "Тривалість",
	"Speed": "Швидкість",
	"%d km/h": "%d км/год",
	"Click a road to see what is there": "Клацніть по дорозі, щоб подивитись, що там",
	"TRAFFIC LIGHT": "СВІТЛОФОР",
	"Phases are netconvert defaults, not observed timings": "Фази — типові значення netconvert, не виміряні",
	"ACTIVE SITUATIONS · %d": "АКТИВНІ ПОДІЇ · %d",
	"Cancel all": "Скасувати всі",
	"Click a road · ESC — cancel": "Клацніть по дорозі · ESC — скасувати",
	"%s · %d lanes · %d km/h · %d m": "%s · %d смуг · %d км/год · %d м",
	"road": "дорога",
	"\nJunction with a traffic light": "\nПерехрестя зі світлофором",
	" · %d s": " · %d с",
	" · road blocked": " · рух перекрито",
	# Bridge errors (tools/situations.py, tools/traffic.py)
	"No road nearby": "Поблизу немає дороги",
	"This road has no lanes for cars": "На цій дорозі немає смуг для авто",
	# Map menu
	"CHOOSE A MAP": "ВИБІР КАРТИ",
	"↑↓ + ENTER or click": "↑↓ + ENTER або клік",
	"  ·  ESC — back": "  ·  ESC — назад",
	"   ·   current": "   ·   зараз",
	"+  New map from any place on Earth…": "+  Нова карта з будь-якого місця на Землі…",
	"Language: English": "Мова: Українська",
	# Location picker
	"NEW MAP": "НОВА КАРТА",
	"Search a place (Enter)": "Пошук місця (Enter)",
	"Latitude, longitude (e.g. 50.45, 30.52)": "Широта, довгота (напр. 50.45, 30.52)",
	"Map name": "Назва карти",
	"Area: %.1f × %.1f km (%.1f km²)": "Площа: %.1f × %.1f км (%.1f км²)",
	"Usually a few minutes": "Зазвичай кілька хвилин",
	"Large area: may take 10–30 minutes and several GB of memory": "Велика площа: може тривати 10–30 хвилин і кілька ГБ пам’яті",
	"Drag — pan · wheel — zoom · click — set the centre": "Тягніть — зсув · колесо — масштаб · клік — центр",
	"Generate": "Згенерувати",
	"Back": "Назад",
	"Cancel": "Скасувати",
	"Searching…": "Пошук…",
	"Nothing found": "Нічого не знайдено",
	"Search failed (HTTP %d)": "Пошук не вдався (HTTP %d)",
	"Invalid coordinates": "Некоректні координати",
	"Starting the generator…": "Запуск генератора…",
	"Downloading OpenStreetMap data from %s…": "Завантаження даних OpenStreetMap з %s…",
	"Could not start the generator: %s": "Не вдалося запустити генератор: %s",
	"Failed: %s": "Помилка: %s",
	"Cancelled; nothing was installed": "Скасовано; нічого не встановлено",
	"Done: %s — loading…": "Готово: %s — завантаження…",
	"Ukrainian road signs (Ukraine only)": "Українські дорожні знаки (лише Україна)",
	"Map tiles unavailable (offline?) — coordinates still work": "Тайли карти недоступні (немає мережі?) — координати працюють",
	"Downloads OpenStreetMap data and terrain. Areas outside Ukraine build without road signs.":
		"Завантажує дані OpenStreetMap і рельєф. Поза Україною карта будується без дорожніх знаків.",
	# Generator stages (akadem_maps progress events)
	"build": "побудова",
	"download": "завантаження",
	"terrain": "рельєф",
	"export": "експорт",
	"install": "встановлення",
}

static var _registered := false

## Registers the Ukrainian table once per process and applies the saved locale.
static func setup() -> void:
	if not _registered:
		var t := Translation.new()
		t.locale = "uk"
		for key in UK:
			t.add_message(key, UK[key])
		TranslationServer.add_translation(t)
		_registered = true
	TranslationServer.set_locale(saved())

static func saved() -> String:
	var cfg := ConfigFile.new()
	if cfg.load(SETTINGS) == OK:
		var value := str(cfg.get_value("ui", "locale", "en"))
		if value in LOCALES:
			return value
	return "en"

static func current() -> String:
	return "uk" if TranslationServer.get_locale().begins_with("uk") else "en"

## Switches between English and Ukrainian and remembers the choice.
static func toggle() -> void:
	var next := "en" if current() == "uk" else "uk"
	var cfg := ConfigFile.new()
	cfg.load(SETTINGS)
	cfg.set_value("ui", "locale", next)
	cfg.save(SETTINGS)
	TranslationServer.set_locale(next)
