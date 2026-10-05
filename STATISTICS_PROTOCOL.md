# Статистика Strategy Council
Дата: 2026-10-05. Дизайн обсуждён Марфой и Алисой в браузерном диалоге; реализация коллектора и полный E2E не подтверждены.

## Три слоя одной картотеки
forecast_validation: неизменяемые прогнозы и отдельные фактические исходы.
execution: реальные либо paper fills, fees/slippage/PnL с явным режимом.
pipeline: доставка, проверки, ревью, возвраты и простои.
Не создавать дубликат картотеки. Сырые события архивируются отдельно от её сводки.

## Как собирать
На каждом новом закрытом origin M5/M15 — snapshot с исходными данными и карточкой каждого разрешённого горизонта.
Минимальная частота outcome collector — закрытые M1; тот же venue и instrument_type.
Forecast snapshot: schema_version, feature_schema_version/SHA, model_version/SHA,
config_sha, profile_sha, history_snapshot_sha, input_snapshot_sha, run_id, event_id,
forecast_id, origin_group_id, origin_type (scheduled/recovery/manual), emitted_at,
market, venue, instrument_type, secid, display_symbol, bar_start_utc, bar_end_utc,
timeframe, horizon, bucket_label, session_bucket, current_price, price_source,
ATR_origin, atr_method, features, center/q10/q90, price_center/low/high,
gate_status/reason, N, ESS, drift, freshness, gaps и source provenance.
current_price — закрытие последней M1 на границе origin. Котировка отправки отдельно.
forecast_id = SHA256 канонического JSON всех instrument/origin/horizon, code/config/profile/schema и history/input snapshot идентификаторов.
run_id в forecast_id не входит. Повтор одинакового snapshot идемпотентен.
Canonical serialization: UTF-8, ключи сортированы, без пробелов, UTC ISO8601 с Z и ровно 3 цифрами миллисекунд; единая нормализация конечных чисел, NaN/Infinity запрещены. Реализация и межъязыковые проверки ещё требуются.
Изменённые входные данные создают новую revision; старый snapshot не переписывать.
origin_group_id связывает горизонты; зависимость проверяется также по интервалам [origin,due_at].

Outcome: forecast_id, due_at, target_bar_end, actual_price, actual_price_source,
observed_at, fwd_available_at, y_atr, return_pct, delivery_latency_ms, label_quality,
status pending/matured/missing/stale, correction/revision provenance.
due_at не является доказательством наличия метки. Никакой интерполяции.
Основная метка — точная целевая закрытая M1; delayed price proxy отдельно.
V1 исследовательский stale threshold: 180 секунд доставки точной свечи; фиксируется до оценки.
Late/backfilled метки храним, availability не задним числом.
В пул исторических аналогов метка допускается только если fwd_available_at <= forecast_origin/as_of и целевая свеча реально получена.
При недостаточных features/данных писать skip/error, не заменять NaN нулями.
У runner v1 NaN feature прерывает прогон; требуется preflight или quarantine, а не обещание автоматического пропуска.

## Что считать
Счётчики: ожидаемые origin, уникальные snapshot, forecast cases, PASS/FAIL_N/FAIL_ESS/FAIL_BOTH/NO_DATA,
skips/errors, duplicate count, ожидаемые/наблюдённые/due/mature/stale/missing outcomes.
Один origin и четыре горизонта не являются четырьмя независимыми торговыми сигналами.
PASS rate считать среди завершённых forecast attempts; отдельно долю завершённых среди ожидаемых.
Maturity completeness считать среди уже due cases, не среди ещё pending.
N/ESS и latency p50/p90/p99; stale/missing rates, exporter/sink queue drops/errors.

Качество основной оценки: только gate PASS + точная зрелая, допустимая метка.
FAIL и stale — отдельные диагностические срезы, число исключений всегда видно.
FAIL_ESS — низкий эффективный размер выборки, не незрелость меток.

Для y=(future-current)/ATR_origin и l=q10,u=q90,c=center:
coverage80 = mean(l<=y<=u); deviation = coverage80-0.8;
MAE_ATR=mean(abs(y-c)); RMSE_ATR=sqrt(mean((y-c)^2));
width_ATR=u-l;
interval_score_0.2=(u-l)+10*(l-y)*I[y<l]+10*(y-u)*I[y>u].
alpha=0.2 — суммарная хвостовая вероятность, по 0.1 с каждой стороны.
Ценовые и процентные ошибки отдельно. ATR после факта не используется.
Flat epsilon=0.25 ATR — заранее фиксированный исследовательский V1, не калиброванный торговый порог.
Классы down/flat/up: abs(delta)<=epsilon ->flat; иначе sign(delta).
Трёхклассовая confusion matrix включает все допустимые cases.
Non-flat accuracy: среди cases с abs(y)>0.25; flat прогноз на non-flat actual считается несовпадением. Actual/forecast flat rates обязательно.
Coverage по ширине интервала: границы bins фиксировать на train, не подбирать на holdout.
Базовые сравнения: zero-change center и train-only калиброванный naive interval на тех же cases/folds.

Разрезы market/venue/instrument_type/secid/timeframe/horizon/bucket/weekday-weekend/model/config/profile.
Выводить sample size и долю исключений. Дневной отчёт описательный, недельный — сравнение с baseline.
CI95%, 1000 block-bootstrap resamples с фиксированным seed и совместным пересэмплированием дней для всех инструментов.
Совместные дневные блоки сохраняют межинструментальную зависимость, независимость акций не предполагается.
V1: фиксированные дневные блоки; для оценки с многодневной зависимостью нужна отдельная заранее фиксированная политика более длинных блоков.
При <30 допустимых cases или <30 day-blocks CI: INSUFFICIENT_SAMPLE; описательные счётчики сохраняются. Это правило отчёта, не порог допуска в production.

## Сделки
entry/exit fill, quantity, direction, fees, slippage, funding для perp, realized/unrealized PnL и drawdown.
Paper и реальные fills не объединять. Прогноз направления не равен прибыльной сделке.
MFE/MAE и TP-before-SL требуют пути high/low; оба касания в одной свече — ambiguous.

## Хранение и работа агентов
Марфа: сбор/экспорт/проверки/доставка точной версии, исправления и сводка.
Алиса: ревью схемы, калибровки и отчёта по реально полученным файлам; исполнения не имитировать.
Raw JSONL/parquet — ограниченные chunks, object archive с checksum/manifest; локальный буфер ротировать.
Не накапливать большие датасеты на PostgreSQL volume 500MB.
Контролировать bytes, свободное место, queue drops и подтверждение архива перед ротацией.
pipeline_log.jsonl хранит события каждого шага, включая сбой до verdict.
Шаг 6 после архивирования/коммита verdict добавляет reviewed_commit и verdict_commit.
Поля: run_id, trigger, source, delivery_attempts, fallback_used, actual manifest verification,
commands/returncode/stdout/stderr, tests counters, e2e_status/reason, findings, verdict,
commit/sync/verdict timestamps, blocked_by, lesha_participation.
Unknown/null не заменять false/PASS. Discussions отдельно от исполняемого code verdict.

## Сейчас
Council v11 развёрнут в shadow для SBER, ROSN, GAZP, NVTK, LKOH, OZON.
Исторический SBER replay не является полным E2E.
Существующий forecast event не доказывает сохранение features и будущих исходов:
полный frozen snapshot/outcome collector ещё требуется реализовать и проверить.
9 MOEX из вчерашней повестки: дополнительные 3 не установлены.
Crypto: NOT_FOR_PRODUCTION, календарь 24/7 и отдельная калибровка ещё требуют реализации.

## Фьючерсы: дополнение 2026-10-05
Отдельный FUTURES_PROFILE.md и dataset_futures_v1.csv, та же картотека.
Общий протокол также распространяется на фьючерсы после собственного market-data/calendar preflight.
Они не входят в нынешний scheduled Council: adapter ограничен шестью акциями.
Задача подключения futures research collector не ждёт crypto calibration.
Фьючерсные дополнения: exact контракт/expiry/specs/ГО и tick value as-of; архив календаря ЕТС/ДСВД;
лентa/delta с coverage, OI и basis availability; entry после доставки, structural stops/ticks/ATR,
real/paper fills, причины отказов и отмен после входа. Риск-отказ не удаляет наблюдение направления.
Статус DESIGN_ONLY / NOT_FOR_PRODUCTION, внедрение и реальный futures E2E не подтверждены.


## Фактический raw запуск 2026-10-05
Raw collector deployed SUCCESS: 2e4ba2bfa9c421a726056591ce2a00f4f432d49a. Два автоматических цикла и readback целостность проверены; 24 records, из них12 observations и12 NO_CLOSED_BARS. Свечей runtime пока0, flow NO_DATA. Полный frozen forecast/outcome collector остаётся незавершённым. Точный отчёт и границы: FUTURES_LAUNCH_2026-10-05.md.
