# `latest_points.json`: последният рън на ICON-EU по точки

Публикува се от MultiConvect в Pages: `https://ilianrvd.github.io/multiconvect/latest_points.json`. Личен проект, не е официален продукт на сертифициран доставчик. Контакт: Илиан Манафов, ilianm@mail.bg.

Формат и обосновка на архива по точки: `docs/archive_points.md` във fogNowcast. Тук е описан самият файл.

## Заглавен блок

Полетата са в началото на файла, по общия заглавен блок на портала (`docs/header.md` в ilianrvd.github.io):

| Поле | Стойност |
|---|---|
| `schema` | `multiconvect.latest_points/1.0` |
| `generated_at` | кога е записан файлът, UTC, ISO 8601 със `Z` |
| `source` | `MultiConvect` |
| `run` | рънът на ICON-EU, ISO низ със `Z` |
| `cadence_min` | `360` |

Старите полета (`model`, `units`, `points`) остават непроменени. Който чете по ключ, не е засегнат. Нови ключове се добавят без смяна на `schema`, а потребителите пренебрегват непознатите.

## Съдържание

```json
{
  "schema": "multiconvect.latest_points/1.0",
  "generated_at": "2026-11-26T10:59:36Z",
  "source": "MultiConvect",
  "run": "2026-11-26T06:00:00Z",
  "cadence_min": 360,
  "model": "icon_eu",
  "units": {"t": "degC", "td": "degC", "wind_kt": "kt", "wind_dir": "deg", "cloud_low_pct": "%", "model_elev_m": "m"},
  "points": [
    {"id": "LBSF", "model_elev_m": 541.6,
     "series": [{"valid": "2026-11-26T06:00:00Z", "lead_h": 0, "t": 2.8, "td": -8.3,
                 "wind_kt": 1, "wind_dir": 34, "cloud_low_pct": 0}]}
  ]
}
```

- 26 точки (5 летища и 21 станции на НТУ, идентификаторите са от общия списък), f000–f030 по часове.
- Стойностите са билинейни от 4-те околни клетки, без корекция по височина. `model_elev_m` е височината на модела в точката.
- Липсваща стойност е `null`. Безветрие (под 1 kt): `wind_dir` е `null`.
- `t` и `td` с 1 знак, `wind_kt`, `wind_dir` и `cloud_low_pct` цели, `wind_dir` в 1–360.
- Пуска се на всеки production рън. `run` е последният пълен рън на ICON-EU, затова може да е по-стар от пускането. Свежестта е по `generated_at`.
