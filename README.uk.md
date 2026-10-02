# Earth2Road — генератор карт (публічна beta, у роботі)

Раніше — TerraDrive. Наявні карти, налаштування, `TerraDrive.cmd` та команди
`terra-drive` і `akadem-maps` залишаються сумісними. Для оновлення наявної інсталяції
запустіть setup ще раз.

[English version](README.md)

Перетворює ділянку OpenStreetMap на відтворюваний, незалежний від рушія **пакет світу** та
експортує його в **BeamNG.drive** (ZIP рівня) і у вбудовану **Godot**-гру.

> **Стан:** експериментальна публічна beta. Репозиторій містить генератор, Godot-гру, тести та синтетичний офлайн-приклад. Реальні карти й завантажені ресурси зберігаються поза Git. Результати перевірок і відомі обмеження — у [VALIDATION](docs/VALIDATION.md).

Розташування доріг і будинки — з OSM. Висоти, фази світлофорів, попит трафіку й оздоблення
вулиць виведені або синтетичні, а не виміряні — кожен запис вказує, що саме.

## Грати — дві команди

Потрібні Python 3.11+ (перевірено 3.14), `curl` та інтернет для першого запуску.

**Windows без терміналу:** завантажте репозиторій (Code → Download ZIP), розпакуйте й двічі
клацніть **`Earth2Road.cmd`**. Перший запуск усе встановить (якщо Python немає, запропонує
встановити його через winget); наступні запуски одразу відкривають гру.

Або з терміналу:

```powershell
.\setup.ps1      # Linux/macOS: ./setup.sh
.\start.ps1      # Linux/macOS: ./start.sh
```

`setup` завантажує Godot 4.6, Python-залежності й моделі машин і встановлює невелику
офлайн-карту для прикладу. `start` запускає гру з трафіком.

Щоб поїздити своїм місцем, у грі натисніть **M → «Нова карта з будь-якого місця на Землі…»**:
знайдіть місце на карті або вставте `lat, lon`, виберіть розмір ділянки (0,3–5 км) і натисніть
**«Згенерувати»**. Гра завантажить дані OpenStreetMap, збудує карту й відкриє її. Керування та
подробиці — у [docs/GAME.md](docs/GAME.md).

Для експорту в BeamNG.drive відкрийте **Карти (M)** та натисніть **Експорт у BeamNG…**
біля потрібної карти. Оберіть папку й натисніть **Експортувати ZIP**. Вікно показує поточний
етап і дозволяє скасувати операцію; після завершення доступні **Відкрити папку** та
**Копіювати шлях до ZIP**. Кожен експорт створює окрему підпапку й зберігає попередні ZIP.
Встановлення ZIP у папку модів BeamNG — вручну. Оберіть режим **Оптимізація** (у вікні є
примітка до кожного; **A+B+C** — для карт у кілька кілометрів, **Оригінал** — еталон). Гра
запам’ятовує папку збереження й режим; для експорту встановлена BeamNG не потрібна.

Усе нижче — для командного рядка: збірка скриптами, експорт і розробка.

## Встановлення генератора

Для зафіксованих залежностей нижче використовуйте Python 3.14. Генератор підтримує Python 3.11+ із сумісними залежностями без lock-файлу. Локально перевірено Windows; для Linux є CI.

```bash
python -m pip install -c requirements.lock ".[generator]"               # з копії репозиторію; на PyPI ще не опубліковано
earth2road doctor                        # перевіряє numpy, shapely, pyproj, osmium, SUMO netconvert
```

`setup.ps1` / `setup.sh` (і `Earth2Road.cmd`) ставлять CLI у локальний `.venv`, а не в `PATH`,
тож просто `earth2road` там «не знайдено». Використовуйте `.\.venv\Scripts\earth2road`
(Linux/macOS: `.venv/bin/earth2road`), спершу активуйте venv (`.\.venv\Scripts\Activate.ps1`,
`source .venv/bin/activate`) або запускайте `python -m akadem_maps` з Python цього venv.

Гравцеві експортованої BeamNG-карти потрібен лише BeamNG.drive — без Python.

## Швидкий старт — повністю офлайн-приклад

```bash
earth2road build  --config examples/tiny/config.json --inputs examples/tiny/inputs --offline --output out/world
earth2road validate --target world  --input out/world
earth2road export --target beamng --world out/world --output out/beamng
earth2road validate --target beamng --input out/beamng
earth2road export --target godot  --world out/world --output out/godot --offline
```

`examples/tiny` — синтетична сітка 3×3 вулиці з пласким рельєфом (MIT), це не дані OSM.

## Власна ділянка (bbox)

```bash
earth2road build --bbox WEST SOUTH EAST NORTH --id my_area --name "Моя ділянка" --output out/my_area
```

- Координати в градусах; `west < east`, `south < north`. Перетин антимеридіана не підтримується.
- Завантажує OSM (Overpass) і тайли рельєфу Mapzen; `--cache DIR` повторно використовує сирі входи.
- Перевірений профіль — `--region-profile ukraine`; будь-яка інша ділянка збирається як
  `experimental` (без дорожніх знаків, стокові номерні знаки, «experimental region» у назві).
- Не беріть завеликі ділянки: кілька км² — хвилини; ділянка ~80 км² збиралась близько 36 хв.
- Зрозумілі помилки: неправильний bbox, порожня дорожня мережа, немає придатної дороги для
  старту, невдале завантаження, відсутні або змінені офлайн-входи.

Кожна збірка пише в **нову** теку, яка з'являється лише після успіху (скасування — Ctrl+C або
SIGTERM, код 130, нічого не публікується). Повторна збірка із записаних входів
`--inputs <world>/inputs --offline` дає ту саму мережу й тайли.

## Експорт у BeamNG

```bash
earth2road export --target beamng --world out/my_area --output out/my_area_beamng [--level-id my_level]
```

`--world` — тека світу: `--output` команди `earth2road build` або `out/generated/<id>` для карти,
створеної в грі (M → New map). Тека `--output` ще не повинна існувати. ID рівня може містити лише
малі латинські літери, цифри та `_`; типово це `kyiv_<ID карти>`. `tools/export_beamng.py
--world <тека> --output <тека>` робить те саме для старих скриптів; його `--map` приймає ID
встановленої карти, як-от `tiny`, а не шлях.

`--optimization balanced` (типово) об'єднує однакові вершини в DAE, спрощує пласкі ділянки ґрунту
(похибка висоти ≤5 см, межі тайлів точні) і дає тротуарам спрощену колізію без фаски бордюру.
`--optimization legacy` записує попередню неоптимізовану геометрію. Додаткові можливості
поєднуються через `+`: `balanced+writer` (A: координати з точністю 1 мм і згладжені нормалі,
DAE ~на 70 % менші), `balanced+kerbs` (B: бордюри без фаски, видимий меш є колізією),
`balanced+terrain` (C: земля як нативний TerrainBlock); `compact` — усі три.
`tools/beamng_bench.py` порівнює ZIP у грі (час завантаження, пам'ять, FPS, скриншоти пліч-о-пліч)
в ізольованих профілях BeamNG. Вимірювання за категоріями —
у `reports/performance.json` (для `--map`: `<output>.performance.json`).

Результат: ZIP рівня, `artifact.json` (SHA-256, версія), `acceptance.json` (статус `pending` —
структурна перевірка не є прийманням у грі) і технічні звіти `reports/`.

Встановлення: скопіюйте ZIP у `%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\mods` (Windows) і
оберіть рівень у Freeroam. Оновлення: замініть ZIP з тією ж назвою; якщо гра показує стару
версію — видаліть `current\temp\levels\<level_id>`. Попередні збірки перевірялись у BeamNG.drive
0.39.x. Синтетичний ZIP цієї версії пройшов перевірку завантаження, поверхні та трафіку; приймання реальних карт залишається окремим кроком. ZIP не містить файлів гри: стокові
дерева, об'єкти й текстури підключаються шляхами, а всі власні ресурси мають префікс ID рівня.

### Збереження правок World Editor

```bash
earth2road capture --target beamng --level "%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\levels\<level_id>" \
                    --export out/my_area_beamng --output my_edits.json
earth2road export --target beamng --world out/my_area_v2 --output out/my_area_beamng_v2 --overrides my_edits.json
```

Зберігаються лише об'єкти сцени (не змінені меші, рельєф чи світлофори). Якщо змінений вами
об'єкт інакше згенерувався в новій збірці, експорт зупиняється й перелічує конфлікти.

## Експорт у Godot

```bash
earth2road export  --target godot --world out/my_area --output out/my_area_godot
earth2road install --target godot --export out/my_area_godot --root . [--replace] [--activate]
```

Встановлення не перезаписує наявну карту без `--replace` (стара копія йде в `.cache/replaced/`)
і змінює активну карту лише з `--activate`. Трафік — SUMO (`pip install ".[traffic]"`).
Керування грою й старі команди: [docs/GAME.md](docs/GAME.md).

## Події для GUI та скриптів

`--events FILE` (або `--events -` у stdout) для будь-якої команди: один JSON-об'єкт на рядок —
`stage` (з монотонним `progress` 0…1), `error` (`code`, `message`) і фінальний `result`.
Читабельний журнал іде в stderr.

## Обмеження

- Висоти наближені (грубий DEM, припущені висоти мостів і з'їздів).
- Фази світлофорів — типові netconvert; попит трафіку синтетичний.
- Доповнення будинків (Overture/Microsoft) необов'язкове й вимкнене для київських карт.
- Linux і macOS не є перевіреними платформами цієї beta (macOS: `setup.sh`, `start.sh`, модульні
  тести та headless-перевірка їзди виконані один раз на Apple Silicon).

## Повідомлення про помилку

Створіть issue з командою, JSONL-файлом `--events`, виводом `earth2road doctor`, ОС і версією
BeamNG, а для проблем карти — ID рівня, координатами або скриншотом. Не прикладайте OSM-витяги
більші за кілька МБ — хешів з `inputs/manifest.json` досить, щоб їх ідентифікувати.

## Ліцензії

Код і згенерована графіка: MIT ([LICENSE](LICENSE)). Дані карт мають власні умови:
© OpenStreetMap contributors, ODbL 1.0 — MIT на них не поширюється. Докладно:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [docs/SOURCES.md](docs/SOURCES.md),
формат світу: [docs/WORLD_FORMAT.md](docs/WORLD_FORMAT.md).

## Development

The distribution and CLI are `earth2road`; `terra-drive` and `akadem-maps` aliases, the `akadem_maps` Python API,
`AKADEM_*` environment variables and existing map IDs remain compatible.
See [CONTRIBUTING](CONTRIBUTING.md), [game setup](docs/GAME.md),
[validation results](docs/VALIDATION.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
