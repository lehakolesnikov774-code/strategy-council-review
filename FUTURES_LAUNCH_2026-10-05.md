# Запуск фьючерсного сборщика
Дата: 2026-10-05. Фактический runtime подтверждён через Railway connector.

## Разделение работы
Марфа: код, интеграция, тесты, deploy и runtime проверка записи/ресурсов.
Алиса: отдельный preflight и статическое ревью фактически переданного inline-кода. Первый ответ: пять MAJOR. После исправлений второй ответ: MAJOR=0, семь non-MAJOR. Алиса не запускала код и не дала production APPROVE.
Дополнительно Марфа исправила null flow/status race и добавила per-contract runtime telemetry.

## Результат
Service trading-signal-bot; deployment e4ba573c-87de-44d8-b098-754115073757 SUCCESS.
Pinned source commit 2e4ba2bfa9c421a726056591ce2a00f4f432d49a.
Runtime version 2.3.9-rc7.78-futures-raw-collector, PAPER, STRATEGY_COUNCIL.
START 2026-10-05T03:37:49.290791913Z = 08:37:49 Asia/Yekaterinburg.
Resolved universe: RNZ6, MXZ6, BRX6, RIZ6, SiZ6, GZZ6.

Два независимых автоматических цикла подтверждены:
- 2026-10-05T03:37:54.338259681Z: 12 records, 13933 bytes, SHA256 d90d1a809e58db3c9046429508ce748f9c2aae69f4d31250ab3340526672d16d, readback_verified=true.
- 2026-10-05T03:38:52.726064078Z: 12 records, 13930 bytes, SHA256 ff4339e9d92bdd73ef377f369aebb2825e08a273f85b241cb9d254031127b1a6, readback_verified=true.

Итого на момент проверки: 24 records: 12 observations +12 NO_CLOSED_BARS diagnostics.
FUTURES_M1=0, feature snapshots=0, flow NO_DATA у всех шести. Это не торговые сигналы и не зрелые outcomes.
Первый цикл quotes stale=true для всех; второй — stale=false у RNZ6/GZZ6 по source timestamp. Это поле само по себе не гарантирует realtime feed.
Данные реально сохранены в существующий object bucket; каждый chunk получен обратно и сверены length/SHA.
M1 сбор включён, но ещё не подтверждён фактической свечой в runtime; календарь и calibrated labels BLOCKED.

## Ресурс
После запуска MEMORY_USAGE_GB current 0.11210752 (~112MB), CPU_USAGE current 0.00920085.
Postgres DISK_USAGE_GB current 0.1042432 (~104MB из500MB), без изменения в проверенном окне.
Новых Postgres записей collector не делает. Очередь4MiB, chunk1MiB, LRU4000.
Это краткая runtime проверка, не восьмичасовой soak test.

## Проверки
Локально futures_collector_v1_smoke.js PASS, npm run check:rc7 PASS, frozen forecaster regression40/40 PASS.
Railway Docker build + preDeploy прошли; runtime SUCCESS.
Test scope: M1 closure/OHLC, unknown volume, duplicates/revisions внутри и между ответами, expiry outage identity stability, retry immutable chunk/backpressure, analyze isolation, split chunks, awaited shutdown и explicit byte overflow.
Full futures forecast/execution E2E: NOT_RUN.
Google Drive raw-chunk delivery, raw trade tape, delta15m, validated futures calendar/outcome/calibration ещё не реализованы.
