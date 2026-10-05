# Историческая фьючерсная база180d: фактический старт
Дата2026-10-05. Лёша уточнил, что нужен исторический аналого-пул, аналогично вчерашней stock выгрузке, а не только текущие observations. Предыдущий raw collector эту задачу не выполнял.

## Что запущено
Raw M1 downloader на Railway, deployment f89b9e03-8de5-4b38-ba8c-ab3a36b23354 SUCCESS.
Source commit98d71ab8d31ef344862a894a1ad42eb68c969d17, version2.3.9-rc7.79-futures-history-180.
START2026-10-05T03:56:20Z (~08:56 Asia/Yekaterinburg).
Запрошенный диапазон2026-04-08..2026-10-04, 180 календарных дней.
Candidates23 exact contracts: RN/MX/RI/Si/GZ × M6,U6,Z6; BR × J6,K6,M6,N6,Q6,U6,V6,X6.
Они выгружаются отдельно. Существование, expiry/specs и ликвидность не угадываются по коду месяца.
Нет склейки цен и автоматического обхода v11 per-secid isolation.

## Фактическое подтверждение
На 2026-10-05T03:57:16.946428966Z: 10000 valid M1 rows для RNM6.
First observed bar 2026-04-08T05:59:00.000Z; last observed bar 2026-04-30T12:02:00.000Z.
Исторический источник ALGOPACK; page500rows, offset10000.
Каждая архивная страница и checkpoint записаны в существующий object bucket и получены обратно с проверкой SHA256.
Последний подтверждённый SHA256: d0f807de13d3a85d1b65b7537fee35e8135c013cdf9a7d0d5da8c73ce46024d8.
Это только начальная часть истории одного контракта. Полные180 дней/23 contracts и метрики прогнозов ещё не подтверждены.

В существующем walkforward/ inventory фактически только6 stock parquet: GAZP,LKOH,NVTK,OZON,ROSN,SBER. Listing complete=true.
Это подтверждение только данного prefix, не заявление об отсутствии любой фьючерсной истории во всём bucket.

## Разделение работ и проверок
Марфа: исторический загрузчик, локальные mock tests, npm run check:rc7, deploy, первые source/S3 records и ресурс.
Алиса: критерии coverage, статическое ревью переданного кода;2 MAJOR (failure budget, corrupt checkpoint loop) исправлены.
Алиса подтвердила устранение по описанным исправлениям, не запускала код, SHA не сверяла и production APPROVE не давала.
Её ошибочные MX=FX и неизменные сроки жизни квартальных/месячных контрактов не приняты.
При corrupted checkpoint задача BLOCKED, данные сохраняются; silent fresh reset не выполняется.

## Что ещё не сделано
Raw job IN_PROGRESS. Full coverage matrix, verified futures calendar/expiry/specs, M5/M15 features/forward labels, отдельная фьючерсная калибровка, repaired runner E2E и walk-forward не завершены.
original_available_at=null, history fetched now: не имитируется исходная realtime availability.
Загрузка продолжается автоматически после ответа, checkpoint сохраняет прогресс; source/coverage errors имеют явный PARTIAL/UNVERIFIED статус.
Штатный raw live collector работает параллельно.
Google Drive raw export и historical tape/OI/GO reconstruction этим M1 загрузчиком не реализованы.
Предварительный темп около500строк/3сек на первом контракте; полный ETA не утверждён, т.к. объём остальных и пустые/ошибочные контракты ещё неизвестны.

## Ресурс
Postgres current0.1042432GB, без роста в проверенном окне. Bot RAM current0.10213376GB (~102MB).
Новое хранилище/таблицы не создавались, raw страницы не пишутся в PostgreSQL.

Технический протокол в production repository: node-bot/FUTURES_HISTORY_180.md.
