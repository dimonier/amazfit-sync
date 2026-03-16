# FPF-анализ метрик из сырых данных Amazfit

## Контекст

Этот разбор опирается только на реально доступные в репозитории носители данных:

- raw daily summaries: `data/raw/band_summary/...`
- raw detailed day payloads: `data/raw/band_detail/...`
- raw workout history: `data/raw/run_history/...`
- normalized day bundle: `data/normalized/latest.json`
- текущий export layer: `amazfit_sync/obsidian_export.py`

FPF-рамка здесь простая:

- `BoundedContext`: повседневная подвижность, восстановление, прокси-самочувствие и долгосрочная физическая активность.
- `Carriers`: raw JSON-файлы и normalized JSON.
- `Claims`: только те показатели, которые можно прозрачно связать с полями источника.
- `Assurance`: каждый показатель ниже помечен по силе как `high`, `medium` или `low`.

## Evidence Graph

### Подтвержденные источники

- `band_summary` работает и содержит дневные сводки сна и активности.
- `band_detail` работает и содержит всё из `band_summary`, плюс дополнительные плотные поля `data` и `data_hr`.
- `run_history` работает и содержит архив тренировок с подробными полями нагрузки.

### Неподтвержденные или недоступные источники

- `sleep_data` -> `404`
- `activity_data` -> `404`
- `workout_data` -> `404`
- `body_data` -> `404`
- `heart_rate` -> `400`

### Ключевой вывод по assurance

- Дневные выводы про шаги и сон сейчас имеют хорошую опору.
- Дневные выводы про ЧСС в течение дня, стресс, HRV, SpO2 и body composition сейчас не имеют достаточной опоры.
- Исторические выводы по тренировкам возможны, но живут в отдельной временной семантике: `run_history` не совпадает с текущим окном `latest.json`.

## Карта доступных сигналов

| FPF Characteristic | Source fields | Что это дает | Assurance |
|---|---|---|---|
| Daily locomotion volume | `stp.ttl`, `stp.dis`, `stp.cal`, `stp.wk` | шаги, дистанция, калории, минуты ходьбы | high |
| Goal compliance | `goal`, `stp.ttl` | процент выполнения дневной цели | high |
| Running share of day | `stp.runDist`, `stp.runCal`, `stp.dis`, `stp.cal` | доля беговой нагрузки внутри дня | medium |
| Activity bout structure | `stp.stage[]` | число эпизодов, длительность, плотность, пиковые окна | high |
| Intra-day distribution | `stp.stepStageSummary[]`, `stp.stage[]` | почасовой и квази-поминутный профиль движения | medium/high |
| Sleep duration | `slp.st`, `slp.ed`, `slp.dp`, `slp.lt` | время в постели и суммарный сон | high |
| Sleep continuity | `slp.stage[]`, `slp.odd_stage`, `slp.wk`, `slp.wc` | фрагментация сна, пробуждения, беспокойство | medium |
| Recovery proxy | `slp.rhr` | resting HR как ночной маркер восстановления | medium/high |
| Sleep structure | `slp.dp`, `slp.lt`, `slp.stage[]`, `slp.ss`, `slp.is`, `slp.lb`, `slp.dt` | глубина сна, доли стадий, прокси качества | medium |
| Workout load history | `run_history.summary[]` fields like `exercise_load`, `te`, `avg_heart_rate`, `max_heart_rate`, `run_time`, `dis` | историческая тренировочная нагрузка | high |
| Dense intra-day series | `band_detail.data`, `band_detail.data_hr` | потенциально минутные/кратные серии активности и HR | low right now, because not decoded |

## Что уже можно извлекать сейчас

## 1. Подвижность в течение дня

### Надежные метрики

- `steps_total`
- `distance_meters`
- `calories_kcal`
- `walk_minutes`
- `goal_steps`
- `goal_completion_pct = steps_total / goal_steps`

### Полезные derived-метрики

- `activity_bout_count`
  - число эпизодов из `stp.stage`
  - отражает, день был дробным или собранным
- `active_stage_minutes`
  - сумма длительностей эпизодов из `stp.stage`
  - полезнее голых шагов для оценки реальной моторной вовлеченности
- `longest_activity_bout_minutes`
  - длина самого длинного непрерывного эпизода
  - хороший индикатор "был ли в дне хотя бы один нормальный блок движения"
- `avg_bout_steps`
  - среднее число шагов на эпизод
  - грубая оценка плотности блока
- `peak_steps_per_minute`
  - максимальная интенсивность по эпизоду
  - годится как простой proxy интенсивности без GPS и без HR-series
- `peak_activity_hour`
  - час с максимальным вкладом в шаги
  - помогает видеть, где у тебя лежит основная двигательная активность: утро, день, вечер
- `movement_fragmentation_index`
  - например: `activity_bout_count / active_stage_minutes`
  - чем выше, тем более рваный паттерн движения
- `purposeful_movement_share`
  - доля шагов, пришедшаяся на длинные или плотные эпизоды
  - позволяет отделять "много мелкой суеты" от целенаправленного движения

### Практический смысл

- шаги сами по себе часто врут про качество дня;
- число эпизодов, длина лучшего эпизода и пик активности дают более правдивую картину подвижности;
- для отслеживания mobility лучше смотреть не на один показатель, а на набор:
  - общий объем;
  - распределение по дню;
  - непрерывность;
  - интенсивность.

### Что видно уже на текущем окне

По текущим 8 дням уже видны полезные диапазоны:

- выполнение цели по шагам: от `39.3%` до `119.1%`
- число эпизодов активности: от `7` до `21`
- активные минуты по `stp.stage`: от `78` до `266`
- длина лучшего эпизода: от `17` до `37` минут

Это уже достаточно, чтобы строить daily mobility dashboard, а не только печатать шаги по часу.

## 2. Самочувствие и восстановление

Слово "самочувствие" здесь надо использовать осторожно. У тебя нет прямой self-report шкалы, поэтому можно говорить только о proxy-маркерах.

### Надежные или относительно надежные proxy

- `total_sleep_minutes = deep + light`
- `time_in_bed_minutes = sleep_end - sleep_start`
- `sleep_efficiency = total_sleep / time_in_bed`
- `deep_sleep_share = deep / (deep + light)`
- `resting_heart_rate`
- `awake_or_restless_minutes`
  - сейчас уже считается как разница между суммой стадий и суммой deep+light

### Дополнительные derived-метрики

- `sleep_fragmentation_index`
  - число переходов стадий или число сегментов `slp.stage`
  - чем выше, тем сон менее непрерывный
- `sleep_regularity`
  - отклонение времени засыпания и подъема от rolling baseline
- `recovery_deviation_score`
  - простой composite proxy на базе:
    - sleep duration vs baseline
    - sleep efficiency vs baseline
    - resting HR vs baseline
  - это именно proxy, не "готовность"
- `resting_hr_delta`
  - разница текущего `rhr` к среднему за 7-14 дней
  - одна из самых практичных вещей для отслеживания недовосстановления
- `short_sleep_streak`
  - серия дней, где сон ниже твоего локального baseline

### Что видно уже на текущем окне

- `resting_heart_rate` ходит примерно в диапазоне `52-58`
- `sleep_efficiency` держится примерно в коридоре `81.5%-85.3%`
- локальное время сна выглядит достаточно регулярным

Это уже позволяет отслеживать не "здоровье вообще", а более честную вещь: устойчивость режима восстановления.

## 3. Глобальные параметры здоровья и физической активности

Здесь важно не врать: по текущим данным можно говорить о долгосрочной активности и восстановлении, но нельзя делать сильные медицинские выводы.

### Что реально можно считать

- `rolling_steps_7d`, `rolling_steps_30d`
- `rolling_distance_7d`, `rolling_distance_30d`
- `goal_hit_rate`
- `activity_variability`
  - вариативность шагов/активных минут/длины лучших эпизодов
- `baseline_resting_hr`
- `baseline_sleep_duration`
- `baseline_sleep_efficiency`
- `activity_monotony`
  - средняя дневная нагрузка / std нагрузки
- `activity_strain_proxy`
  - monotony * суммарная нагрузка
- `running_load_history`
  - из `run_history`: частота тренировок, длительность, дистанция, `exercise_load`, `te`, `anaerobic_te`

### Что особенно ценно в `run_history`

Там уже есть поля, которых нет в day bundle:

- `exercise_load`
- `te`
- `anaerobic_te`
- `avg_heart_rate`
- `max_heart_rate`
- `run_time`
- `highPrecisionDistance`
- `heart_range`

То есть для long-term athletic profile у тебя уже есть куда более сильный материал, чем текущий Markdown показывает.

### Но есть важное ограничение

Текущий `run_history` в рабочем raw-файле не ограничен окном normalized bundle. В нем есть записи от старых лет до конца `2025-12-10`. Значит:

- его нельзя бездумно смешивать с day-centric bundle;
- его надо либо отдельно нормализовать как workout history stream;
- либо фильтровать по окну перед интеграцией в daily export.

## Что пока нельзя честно утверждать

Ниже список метрик, которые сейчас либо недоступны, либо слишком слабо обоснованы:

- HRV
- stress
- SpO2 trends
- body fat / weight / body composition
- true readiness score
- illness risk
- overtraining risk в строгом смысле
- precise cardio zones inside daily life
- reliable sedentary time
- true gait quality
- GPS-based route quality, elevation load, terrain impact

Причина не философская, а техническая:

- часть endpoint'ов не работает;
- часть данных есть только в непрозрачных `data` / `data_hr`;
- часть серий не декодируется текущим кодом;
- часть источников вообще не попадает в normalized bundle.

## Что стоит добавить в нормализацию

Если говорить прагматично, то наибольший выигрыш дадут не абстрактные новые индексы, а следующие шаги:

1. Декодировать `band_detail.data` и `band_detail.data_hr`.
2. Явно нормализовать derived-метрики по активности:
   - `activity_bout_count`
   - `active_stage_minutes`
   - `longest_activity_bout_minutes`
   - `peak_activity_hour`
   - `peak_steps_per_minute`
3. Явно нормализовать derived-метрики по восстановлению:
   - `sleep_efficiency`
   - `deep_sleep_share`
   - `sleep_fragmentation_index`
   - `resting_hr_delta`
4. Выделить `run_history` в отдельный normalized stream, а не пытаться засунуть его в текущую логику `days[].workouts` без фильтра по дате.

## Рекомендации по Markdown-экспорту

Текущий export в `amazfit_sync/obsidian_export.py` делает минимум:

- `Steps`
- `Active walking minutes`
- базовый `Sleep`
- `Steps By Hour`

Для человека этого мало. Для аналитики это почти бесполезно.

## 1. Что менять концептуально

Markdown должен быть не сырой распечаткой, а `curated view` над normalized JSON.

Лучший формат:

- короткий daily dashboard наверху;
- derived insights посередине;
- raw/evidence appendix внизу;
- явные метки `derived`, `proxy`, `missing source`.

## 2. Рекомендуемая структура заметки

### Frontmatter

Стоит добавить ключевые поля для Obsidian и downstream-обработки:

- `date`
- `steps_total`
- `goal_steps`
- `goal_completion_pct`
- `distance_meters`
- `calories_kcal`
- `walk_minutes`
- `run_distance_meters`
- `sleep_minutes`
- `sleep_efficiency`
- `resting_heart_rate`
- `activity_bout_count`
- `longest_activity_bout_minutes`
- `data_quality_flags`

### Блок `Summary`

Оставить только 5-8 главных метрик:

- шаги
- процент выполнения цели
- дистанция
- калории
- минуты активности
- беговая доля
- сон
- resting HR

### Блок `Activity`

Добавить:

- `goal_completion_pct`
- `distance_meters`
- `calories_kcal`
- `run_distance_meters`
- `run_share_pct`
- `activity_bout_count`
- `active_stage_minutes`
- `longest_activity_bout_minutes`
- `peak_activity_hour`
- `peak_steps_per_minute`

### Блок `Recovery`

Добавить:

- время сна
- время в постели
- эффективность сна
- deep/light ratio
- awake/restless minutes
- fragmentation proxy
- resting HR
- отклонение `rhr` от baseline, если baseline уже есть

### Блок `Trends`

Если окно достаточно длинное, выводить:

- среднее за 7 дней
- отклонение от среднего
- серия дней ниже цели
- серия дней с коротким сном

### Блок `Data Quality`

Это очень важно. Надо явно писать:

- какие источники использованы;
- какие источники недоступны;
- какие выводы являются proxy;
- какие секции отсутствуют не потому что "ничего не было", а потому что источник недоступен или не попал во временное окно.

## 3. Что не стоит делать в экспорте

- Не надо печатать тяжелые JSON-блоки по умолчанию, если они не помогают читать день.
- Не надо скрывать пустые `heart_rate`, `workouts`, `body_metrics` так, будто это нормальная полнота данных.
- Не надо рисовать composite scores типа "готовность 78/100" без отдельного описания formula и статуса proxy.

## 4. Практически полезный минимальный upgrade экспорта

Если делать только одно небольшое улучшение, я бы добавил в экспорт вот этот набор:

- `steps_total`
- `goal_completion_pct`
- `distance_meters`
- `calories_kcal`
- `run_distance_meters`
- `activity_bout_count`
- `longest_activity_bout_minutes`
- `sleep_minutes`
- `sleep_efficiency`
- `resting_heart_rate`
- `Data Quality`

Это уже резко лучше текущего состояния и при этом не требует фантазий.

## Жесткий вывод

Из текущих raw-данных уже можно собрать вполне полезную систему наблюдения за:

- реальной подвижностью в течение дня;
- качеством и регулярностью восстановления;
- долгосрочной тренировочной нагрузкой;
- отклонениями от собственного baseline.

Но нельзя честно делать вид, что у тебя уже есть полноценный health dashboard. Сейчас у тебя есть:

- хороший базис по шагам, сну и workout history;
- скрытый, но пока не освоенный потенциал в `band_detail.data` и `band_detail.data_hr`;
- слабое покрытие по физиологическим маркерам вне сна;
- слишком бедный Markdown-экспорт, который скрывает большую часть уже доступной ценности.

Если нужен максимальный practical impact, приоритет такой:

1. Расширить normalized layer derived-метриками активности и сна.
2. Перестроить Markdown-экспорт в curated dashboard.
3. Декодировать `band_detail.data` и `band_detail.data_hr`.
4. Нормализовать `run_history` как отдельный поток long-term athletic metrics.
