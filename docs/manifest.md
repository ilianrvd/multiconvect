# `manifest.json` на MultiConvect

Публикува се в `https://ilianrvd.github.io/multiconvect/manifest.json`. Форматът е на портала: `docs/manifest.md` в `ilianrvd/ilianrvd.github.io`. Личен проект, не е официален продукт на сертифициран доставчик. Контакт: Илиан Манафов, ilianm@mail.bg.

Пише се в края на всяко production пускане от `tools/manifest_json.py` и влиза в същия deploy. Стъпката е независима: ако се провали, сайтът се публикува без манифест.

## Продукти

| `id` | Файл | Формат | `schema` | Описание |
|---|---|---|---|---|
| `latest_points` | `latest_points.json` | json | `multiconvect.latest_points/1.0` | [`latest_points.md`](latest_points.md) |
| `fog_fields` | `fog_fields_icon_eu.npz` (и `fog_fields_meta.json` в ключа `meta`) | npz | `multiconvect.fog_fields/1.0` | [`fog_fields.md`](fog_fields.md) |

- `cadence_min` е 360 за проекта и за двата продукта.
- `generated_at` на всеки продукт е от самия му файл, а `data_time` е рънът на ICON-EU. Порталът мери свежестта по `generated_at`, не по `run`.
- Продукт се вписва само ако файлът му е записан в това пускане. При провал продуктът отсъства от манифеста, а от Pages също (сайтът се публикува наново целият).
- `run` на манифеста е `{"icon_eu": <най-новият рън на продуктите>}`. Липсва, когато няма продукти.
- `status` е `experimental`. Манифестът не съдържа `consumes`: MultiConvect не чете други проекти за тези продукти.
