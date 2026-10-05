# Контракт реальных E2E-датасетов
Дата: 2026-10-05. Это схема, не созданный реальный датасет.

Файлы dataset_moex_v1.csv и dataset_crypto_v1.csv раздельные.
По одному календарю, venue/type и неизменяемому feature_schema на прогон.
Manifest: SHA256 файлов, source, market/venue/type, period, rows, missing/duplicates,
calendar/profile/config SHA, schema version, bar closure evidence, label provenance.

Шесть базовых колонок недостаточны. Требуются feature__* и cross_session_*;
для численных quality metrics нужны зрелые fwd_ret_* и fwd_available_at_*.
timestamp = timezone-aware UTC bar_end. Только фактически закрытые исходные свечи.
current_price>0, atr>0, конечные числа; no fake zero features.
fwd_ret в v11 — ATR-normalized price delta, не процент.

Порядок заголовка:
timestamp,timeframe,session_bucket,secid,current_price,atr,
feature__atr1m_pct,feature__realized_vol1m_pct,feature__momentum5m_pct,
feature__momentum15m_pct,feature__momentum30m_pct,feature__local_slope_pct_per_bar,
feature__t1_slope_pct_per_bar,feature__t5_slope_pct_per_bar,
feature__t15_slope_pct_per_bar,feature__volume_ratio,feature__drift_pct,
cross_session_30m,cross_session_60m,cross_session_90m,cross_session_120m,
fwd_ret_30m,fwd_ret_60m,fwd_ret_90m,fwd_ret_120m,
fwd_available_at_30m,fwd_available_at_60m,fwd_available_at_90m,fwd_available_at_120m.
Дополнительные audit поля допустимы; feature__ префикс только для действительных features.
Boolean export: true/false. Пустая незрелая метка остаётся пустой, не 0.

MOEX подтверждённый calibration universe:
SBER,ROSN,GAZP,NVTK,LKOH,OZON. Ещё 3 названия не установлены.
Исторический маппинг bucket должен совпадать с live и быть явно версионирован:
не заменять его приблизительным описанием первых/последних минут сессии.
Crypto: только новый CRYPTO_UTC6_V1 и отдельный календарь 24/7; qualified secid из CRYPTO_PROFILE.md.
30m=M5;60/90/120m=M15.

## Два MAJOR runner v1
1. fc.history напрямую обходит cutoff base_days. Перед каждым origin нужен fc.load_history(pool,current.timestamp).
2. summary valid не проверяет gate PASS и включает FAIL с ненулевыми квантилями.
Исправление: PASS + зрелая/качественная actual метка; FAIL отдельный отчёт.
reproduce_runner_issues.py фактически исполнялся Марфой:
MAJOR-1: direct history assignment PASS; load_history NO_DATA
MAJOR-2: FAIL_BOTH counted by runner-v1 quality predicate
Команда из корня пакета: python3 reproduce_runner_issues.py.
Канонические v11 и runner v1 сохранены для независимого воспроизведения; исправления не представлены как выполненные.

## Приоритет
1. Исправить runner и провести preflight реального MOEX export.
2. Frozen snapshots/outcome collector MOEX; параллельно crypto raw capture и календарь.
3. Раздельные E2E с фактическим stdout/returncode, включая delivery/export/provenance.
4. Затем walk-forward и калибровка крипты.
Первый день — smoke, не калибровка. Не обещать число зрелых меток заранее.
Полный E2E на реальном датасете сейчас NOT_RUN.

## Фьючерсное расширение
Отдельный dataset_futures_v1.csv. Общие6колонок+feature__11+cross_session/fwd_ret/fwd_available_at сохраняются.
Дополнительные audit поля: exchange,board,instrument_type=futures,resolved_secid,expiry_at,
underlying_id,contract_spec_sha,calendar_sha,horizon_clock=TRADING_MINUTES,
exchange_calendar_date,exchange_trading_day_id,bar_type,trading_status,
trading_target_ts_30m/60m/90m/120m,wallclock_reference_ts_30m/60m/90m/120m,
metadata/input_snapshot ids,availability/quality.
Лента/OI/ГО/basis/tradeids хранятся в sidecar с join по snapshot_id; новые feature__ не добавлять в frozen v11.
Пул exact контракт, не underlying и не склейка expiry. Один календарь/профиль на прогон.
Runner v1 создаёт TradingCalendar() сам: futures calendar selection ещё надо реализовать и проверить,
одного разделения CSV недостаточно. Не запускать futures E2E со stock calendar под видом валидации.
Реальный futures dataset и E2E в этом обсуждении NOT_RUN. Подробности в FUTURES_PROFILE.md.
