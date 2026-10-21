## Context

Резервы живут в `InMemoryStore` как `ReservationRecord` (статус `EXPIRED` не хранится, вычисляется по `now`). `Inventory` читает время один раз на операцию, проверяет всё до изменений и пишет события в `EventLog`. Требования — в specs/stock-reservations/spec.md, мотивация — в proposal.md.

## Goals / Non-Goals

**Goals:** замена активного резерва, возврат по подтверждённому заказу, TTL 20 минут, предел срока 2 часа, `reservations`, `availability`, `sweep_expired`.

**Non-Goals:** фоновые процессы, изменения `cli.py`/`reports.py`, формата журнала, новые зависимости, изменение существующих тестов.

## Decisions

1. **Предел — 2 часа.** В описании задачи 1 час, в обсуждении склад согласовал 2 (позднее решение): `MAX_RESERVATION_LIFETIME = timedelta(hours=2)` в `warehouse/reservations.py`. `DEFAULT_RESERVATION_TTL = timedelta(minutes=20)`.
2. **Валидация ttl.** `resolve_ttl` проверяет форму (как раньше); предел проверяется только в `reserve` (`ttl > MAX` → `ValidationError`), чтобы `extend` не падал. Для `extend`: `new = min(now + ttl, created_at + MAX)`; обновление и событие только при `new > expires_at`.
3. **Замена в `reserve`.** Порядок: валидация `order_id`, ttl (включая предел), строк → статус существующего: `CONFIRMED` → `DuplicateReservationError`; `ACTIVE` → замена; иначе обычная перезапись. Проверка наличия для замены считает `available` без вклада заменяемой записи (`reserved_qty` минус строки старой записи по позиции, не ниже нуля после общей формулы `max(0, on_hand - reserved_без_старой)`). Затем запись нового `ReservationRecord` (новые `created_at`, срок), события: при замене `RESERVE_CANCEL`, затем `RESERVE` по строкам. Все проверки раньше изменений ⇒ атомарность, журнал при ошибке не меняется.
4. **Возврат в `cancel`.** Для `CONFIRMED`: вернуть физический остаток по строкам (без публичного `receive`, чтобы одно `now` и атомарность; но события тем же форматом: `RECEIVE` с `wh`, `sku`, `qty`, `ref=order_id`), статус записи → `CANCELLED`, затем `RESERVE_CANCEL`. Повторный `cancel` уходит в существующую ветку «уже `CANCELLED`» без событий.
5. **`sweep_expired`.** В `ReservationRecord` добавляется поле `expire_logged: bool = False`. Выбираются записи с хранимым статусом `ACTIVE`, `now >= expires_at`, `not expire_logged`; сортировка по `(expires_at, order_id)`; для каждой `RESERVE_EXPIRE(order, expires)` и `expire_logged = True`. Признак относится к записи, а не к заказу, поэтому новый резерв того же заказа (новая запись) отчитывается отдельно (комментарий Игоря Левина). Для этого store получает метод перебора записей `(order_id, record)`.
6. **`reservations(status)`.** Снимки всех записей через `_snapshot`, фильтр по `status_at(now)`, сортировка `(created_at, order_id)`. `get_reservation` и запросы остаются без побочных эффектов.
7. **`availability(warehouse)`.** Ключи — объединение позиций с ненулевым физическим остатком и позиций с активным резервом (по строкам действующих записей); сортировка `(warehouse, sku)`, фильтр по складу; значения через те же `on_hand`/`reserved`/`_available` на одном `now`. Модель `Availability` — frozen dataclass в `models.py`.
8. **Экспорты.** `Availability` и `MAX_RESERVATION_LIFETIME` добавляются в `warehouse/__init__.py` и `__all__`.

### Допущения

- Резерв, истёкший и заменённый новым до вызова `sweep_expired`, не отчитывается (запись заменена, «полная замена» из прежней спецификации).
- Событие `RESERVE_EXPIRE` пишется со временем вызова `sweep_expired` (округление до секунды — как у всех событий), `expires` — срок резерва.
- Возврат допустим и после `expires_at` подтверждённого резерва (подтверждённый статус окончательный).
- Заказ после возврата (`CANCELLED`) можно резервировать снова.
- `extend` с `ttl` выше предела не ошибка даже при `ttl` > 2 часов.
- Существующие тесты на отменённые правила (TTL 15 минут в `tests/test_reservations.py`, `test_duplicate_active_and_confirmed_even_after_expiry`, `test_cancel_expired_and_confirmed`, а также места, где `clock.advance(timedelta(minutes=15))` рассчитано на старый TTL) упадут; по условию задачи они не правятся, список фиксируется в отчёте.

## Risks / Trade-offs

- [Устаревшие тесты падают] → зафиксировать список в отчёте реализации, новые проверки — в новых тестовых файлах.
- [Потребители журнала не знают `RESERVE_EXPIRE`] → формат строки не меняется, тип события новый; уведомить потребителей выгрузки.
- [Не отчитанный и заменённый истёкший резерв не попадает в `sweep_expired`] → принято как допущение.
- [Перебор всех записей в `reservations`/`sweep_expired`/`availability`] → объёмы малы, хранилище в памяти.
