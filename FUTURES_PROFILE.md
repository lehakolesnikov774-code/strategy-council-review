# FUTURES_PROFILE_V1
Дата: 2026-10-05. Статус: DESIGN_ONLY / NOT_FOR_PRODUCTION.
Дополнение к общей STATISTICS_PROTOCOL.md, та же картотека. Не заявление о внедрённом сборе.

## Текущее ограничение
Проверен исходник deployed commit df7e518b0712644a748e19e48cdbd9825260bec9:
node-bot/strategy_council_rc7.js ограничен STOCKS шестью акциями;
node-bot/bot_v23.js councilMonitorCycle берёт только Council instruments.
Фьючерсы из APPROVED поэтому не входят в scheduled Council forecasts.
BKS hub содержит ленту/flow функции, но это не подтверждение полного frozen snapshot/outcome сборщика.
Live freshness, фактическая запись и E2E фьючерсов в этом обсуждении не проверены.

## Universe
Первичная группа по проверенному исходнику: RNZ6, MXZ6, RIZ6, SiZ6 и runtime-resolved Brent.
Brent resolution сохраняет BRENT_SECID override либо результат nextMonthBrentSecid + время/причину выбора.
Старый BRV6 не назначается активным по памяти. Resolution failure -> NO_DATA.
GZZ6, SRZ6, ONZ6, NAZ6, SFZ6, GDZ6, SVZ6, CRZ6 обозначены researchOnly в коде;
это реальные инструменты, researchOnly — режим бота, не свойство биржевого контракта.
Включение каждого инструмента в новый сбор требует market-data preflight, а не автоматического торгового допуска.
Exact identity: exchange/board/secid/expiry; underlying отдельно.
Не смешивать разные expiry/поставочные и расчётные контракты/валюты котирования.
ROSN — underlying для RNZ6; индекс РТС — для RIZ6.

## Календарь и lifetime
Отдельный FuturesTradingCalendar, тот же интерфейс вычислений времени v11;
архив schedule as-of по дате, контракту, торговому статусу, eligible выходным и аукционам.
Расчётный клиринг не считать остановкой торговли.
Официальная страница MOEX сообщает ЕТС с 23.03.2026 и отсутствие промежуточной остановки;
верхнее расписание и FAQ расходятся по утреннему старту, поэтому часы не копировать в код без датированной проверки.
Отдельные exchange_calendar_date и exchange_trading_day_id: ДСВД может относиться к следующему торговому дню.
bar_type continuous/auction/pre_open/post_close плюс trading_status/halt отдельно.
price_limit_hit не означает halt. Limit regime остаётся в диагностике, без отбора после исхода.
Origin только из закрытых continuous M1, агрегированных до M5/M15, без синтетических пропусков.
В основной V1 метке horizon_clock=TRADING_MINUTES, H=30/60/90/120.
trading_target_ts — H минут разрешённого continuous расписания после origin.
wallclock_reference_ts=origin+H обычных минут; due_at=trading_target_ts.
Target за lifetime -> EXPIRED_UNOBSERVABLE, не successor price.
cross_session определяется фактическим разрывом торгового времени, не названием bucket.
Аукцион/реальный halt/неполные данные явно отмечаются; неизвестный calendar -> CALENDAR_UNVERIFIED.
Отсутствующая свеча не превращается в календарный перерыв.

## Raw и sidecar
Закрытые M1: begin/end UTC, OHLCV, trades_count, bar_type, trading_status, source и received_at.
Bid/ask/spread ticks+ATR, depth если доступен, source_ts/quote_age.
Trades: exchange/provider id если существует, source_event_id, seq, price, quantity_contracts,
provider_side, side_semantics_version, source_ts, received_at, unknown_side_count.
Не объявлять BUY/SELL доказанным aggressor без проверки документации поставщика.
delta1m/5m/15m = известные BUY contracts - SELL contracts.
Unknown-side volume и полнота окон отдельно. Cumulative delta segment/session с reset_reason и coverage.
Рестарт/reconnect разрывает доказанную полноту; session total PARTIAL при непокрытом gap.
Текущий BKS hub хранит около 11 минут events, выдаёт5m/prior5m и reset по UTCdate.
Для delta15m и exchange_trading_day_id требуется доработка.
normalizeTrade синтезирует TRADENO из timestamp: это не exchange tradeid и не гарантия уникальности.
Если надёжного id нет, dedup_quality=UNVERIFIED, никаких exactly-once обещаний.

OI, delta_OI, ГО биржи, broker_margin, step_price, min_step, price limits,
contract_size, quote/settlement currencies, last_trade/expiry times:
value/source/effective_at/published_at/observed_at/revision.
Unknown=null, не0. Независимый источник/частота каждого поля в manifest.
Availability по фактическому получению, не фиксированному20:00.
Basis: только синхронные цены и нормализованные contract units/currency;
basis_available/reason, underlying_price_ts, conversion_source/version.
Roll registry: old/new secid, planned/effective/observed times, liquidity criterion, provenance;
выбор на основе известного as-of объёма/OI, не будущих итогов дня.
Фронт-серии не склеивать для labels. Любое cross-contract обучение — отдельный профиль/ревью.
Новости/Brent/рубль/пара/лидер/лаг сохраняются с availability. Нет причинности по одной корреляции.

## Forecast/outcome
Общая frozen snapshot схема + expiry, contract_spec_sha, calendar_sha, horizon_clock,
resolved_secid, board, liquidity/expiry regime, sidecar ids.
Model feature schema11 v11 не расширяется лентой/OI без новой версии, исторических features и ревью.
Content hash включает все входы прогноза; underlying не target, но входит в hash если влияет на forecast.
30m=M5,60/90/120m=M15. Outcome exact contract и target candle.
y=(future_price-current_price)/ATR_origin; проценты отдельно; availability<=as_of для исторических аналогов.
Missing/stale/expired/gaps отдельно, никаких фиктивных нулей.
Frozen ATR method должен совпадать с историческим профилем.
Фьючерсная калибровка отдельная; stock CAL_V1 не является готовой futures calibration.

## Execution, стопы и пропуски
Отдельно от forecast accuracy: signal_id, forecast_id, setup TREND/PULLBACK/BREAKOUT/REVERSAL,
created_at/sent_at/delivered_at + evidence_quality, valid_until, LONG/SHORT,
entry_zone, structural_stop/source, distance ticks/ATR, TP1/TP2, integer qty,
plannedrisk рублей, ГО на входе/изменения/выходе, commissions, margin exposure и cancellation reason.
Нет доказанного client delivery -> не подменять sent_at delivered_at; отдельная proxy аналитика.
Opportunity только после delivered_at до valid_until; executable Ask для LONG, Bid для SHORT.
Quote touch -> PAPER_CANDIDATE, не реальное исполнение и не гарантия limit fill.
Paper fill model + version + depth/capacity evidence. Без depth CAPACITY_UNVERIFIED.
V1 sensitivity scenarios: 0/1/2 adverse ticks сверх соответствующего bid/ask,
не калиброванный market-impact model; не учитывать spread дважды.
Real fills только из подтверждённых execution records/manual report с provenance.
PnL по fills и соответствующей контракту биржевой/broker модели; frozen STEPPRICE — planned estimate.
Cost-of-carry — pricing context для обоих типов, не автоматически комиссия.
Учитывать только фактические fees/financing, без двойного вычета carry/variation margin.
TP/SL и MFE/MAE после входа, M1 или trades path; оба касания в одном баре -> AMBIGUOUS.
exit_reason TP/SL/manual_close/expiry/margin_call отдельно.
Cancellation после входа не стирает позицию и не считается отсутствием входа.
WAIT/MISSED/NO_DATA/NO_TRADE/risk rejection сохраняются; исследования направления не подавляются sizing gate.
Нет данных для counterfactual после отказа -> UNOBSERVED, не0 PnL.
Delivery latency и missed move до доставки отдельно от цены после доставки.

## Сводки
Общие coverage80, MAE/RMSE_ATR, interval_score0.2, sign confusion/flat rates, PASS/N/ESS;
completion/stale/missing rates, spread/liquidity, tape coverage, OI freshness, skipped origins.
Сигналы: entry reachability, delivery delay, oversize, stop distance, TP-before-SL, MFE/MAE,
отмены после входа, risk rejections, paper vs real netPnL с явными знаменателями.
Разрезы exact contract/underlying class/expiry regime/session/trading_day/model/profile.
Независимость RNZ6 и ROSN не предполагается; bootstrap общими trading-day блоками.
50–100 сделок — цель накопления наблюдений, не доказательство статистической значимости.
Один день — smoke; CI политика общей схемы, малый sample -> INSUFFICIENT_SAMPLE.

## Следующий этап
1. Исправить два MAJOR общего E2E runner; marketdata/calendar/spec preflight каждого контракта.
2. Futures schedule adapter и отдельный bounded snapshot/outcome writer, параллельно crypto.
3. Подключить futures к scheduled research path и подтвердить реальными raw+outcome файлами.
4. dataset_futures_v1.csv + sidecar JSONL/parquet + manifests, отдельный E2E и calibration.
Сырой сбор/отказы не должны ждать наличия достаточной истории для PASS.
Не заявлять запуск до фактического deploy и наблюдения записей.
Резервирование/выгрузка в единственную картотеку/долговременные данные, guards60/75/85%, bounded queues;
не накапливать полную ленту на PostgreSQL volume500MB.

## Источники проверены 2026-10-05
- https://www.moex.com/ru/derivatives/unified-trading-session — ЕТС, клиринг, ДСВД, экспирация; расхождение утренних часов требует as-of проверки.
- https://moexalgo.github.io/docs/description/realtime/ — поля futures M1/trades/specs/OI/MINSTEP/STEPPRICE/INITIALMARGIN.
- trading-signal-bot commit df7e518b0712644a748e19e48cdbd9825260bec9, node-bot/bot_v23.js, strategy_council_rc7.js, bks_tape_hub.js.


## Фактический raw запуск 2026-10-05
Raw collector deployed SUCCESS: 2e4ba2bfa9c421a726056591ce2a00f4f432d49a. Два автоматических цикла и readback целостность проверены; 24 records, из них12 observations и12 NO_CLOSED_BARS. Свечей runtime пока0, flow NO_DATA. Полный frozen forecast/outcome collector остаётся незавершённым. Точный отчёт и границы: FUTURES_LAUNCH_2026-10-05.md.
