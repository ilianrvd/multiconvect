# Мрежови полета на ICON-EU за fogNowcast: `fog_fields_icon_eu.npz`

Файловете се създават от MultiConvect и се публикуват в Pages до `latest_points.json`:

- `https://ilianrvd.github.io/multiconvect/fog_fields_icon_eu.npz`
- `https://ilianrvd.github.io/multiconvect/fog_fields_meta.json`

Личен проект, не е официален продукт на сертифициран доставчик. Контакт: Илиан Манафов, ilianm@mail.bg.

Форматът е съгласуван с fogNowcast на 2026-11-26 (виж `docs/input_multiconvect.md` там). Файлът се чете в Actions, не в браузъра.

## Откъде идват данните

Същите GRIB полета на ICON-EU (DWD Open Data), които `tools/points_run.py` вече тегли за `latest_points.json`. Няма допълнително теглене. И двата продукта идват от **едно и също пускане**, затова `run` и `generated_at` са еднакви в `fog_fields_meta.json` и `latest_points.json`.

## Обхват

- Район: 40.3–45.1 N, 21.1–31.3 E (`domain` в `config/config.yaml`), клетките, чиито центрове попадат в него. Нативна мрежа 0.0625°, без превъртане.
- Часове: f000–f030 по часове (31). Рънове 00, 06, 12 и 18 UTC. `cadence_min` е 360.
- Само ICON-EU. GFS и IFS не са включени.

## `fog_fields_meta.json`

```json
{
  "schema": "multiconvect.fog_fields/1.0",
  "generated_at": "2026-11-26T10:59:36Z",
  "source": "MultiConvect",
  "run": "2026-11-26T06:00:00Z",
  "cadence_min": 360,
  "models": {"icon_eu": {"file": "fog_fields_icon_eu.npz", "time_step_h": 1, "interpolated_hours": []}},
  "grid": {"lat_min": 40.3125, "lat_max": 45.0625, "lon_min": 21.1875, "lon_max": 31.25,
           "step_deg": 0.0625, "ny": 77, "nx": 160, "hours": 31, "lat_order": "ascending"},
  "vars": {
    "t2m":  {"units": "degC", "scale": 0.01, "offset": 0.0, "fill": -32768, "dtype": "int16"},
    "hsurf": {"units": "m", "scale": 1.0, "offset": 0.0, "fill": -32768, "dtype": "int16", "static": true}
  }
}
```

- Заглавният блок е `schema`, `generated_at`, `source`, `run`, `cadence_min`. Времената са UTC, ISO 8601 със `Z`.
- `run` е ISO низ на рънa на ICON-EU и е равен на `run` в `latest_points.json`. Когато се добавят други модели, рънът на всеки модел отива в `models.<модел>.run`.
- `vars` описва всяка променлива: `units`, `scale`, `offset`, `fill`, `dtype`. `static: true` е за променлива без време.
- Потребителите **пренебрегват непознати ключове**. Нова променлива се добавя във `vars` и в `.npz` без смяна на `schema`.

## `fog_fields_icon_eu.npz`

| Масив | Форма | Тип | Съдържание |
|---|---|---|---|
| `lat` | `(ny,)` | float32 | градуси, **във възходящ ред** |
| `lon` | `(nx,)` | float32 | градуси, във възходящ ред |
| `valid_time` | `(nt,)` | int64 | секунди от 1970-01-01 UTC, на час |
| `hsurf` | `(ny, nx)` | int16 | височина на клетката, m (статично) |
| `t2m` | `(nt, ny, nx)` | int16 | температура на 2 m, °C |
| `td2m` | `(nt, ny, nx)` | int16 | точка на оросяване на 2 m, °C |
| `u10` | `(nt, ny, nx)` | int16 | зонална компонента на вятъра на 10 m, **kt** |
| `v10` | `(nt, ny, nx)` | int16 | меридионална компонента на вятъра на 10 m, **kt** |
| `clcl` | `(nt, ny, nx)` | int16 | ниска облачност, % |

Стойността е `raw * scale + offset`. Мащабите са: `t2m`, `td2m`, `u10`, `v10` по 0.01, `clcl` по 0.1, `hsurf` по 1. `u10` и `v10` се превръщат от m/s в kt при запис, температурите от K в °C.

**Липсваща стойност:** `raw == fill` (−32768). Това е и NaN, и стойност извън обхвата на int16, и цял липсващ час. `u10` и `v10` са компоненти, не скорост и посока: посоката се смята при потребителя (откъдето духа, `atan2(-u, -v)`).

## Добавяне на променливи по-късно

`vis` и `ww` не са включени сега. При добавяне: `vis` в m не се побира в int16 с мащаб 1 (до около 70 km), затова иска мащаб около 2 m. `ww` е категориен код и пасва на `uint8`. Това е причината за `dtype` във `vars`.
