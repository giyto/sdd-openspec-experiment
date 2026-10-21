## Purpose

Описывает новые статусы заданий `RETRY_SCHEDULED` и `DEAD_LETTERED` и их согласованность со статистикой, отменой, очисткой и отчётом дежурных.

## ADDED Requirements

### Requirement: Новые статусы
Система SHALL поддерживать статусы `RETRY_SCHEDULED` со значением `"retry_scheduled"` и `DEAD_LETTERED` со значением `"dead_lettered"`. `stats()` и `list_jobs(status)` SHALL учитывать их. `is_terminal` SHALL быть `True` для `DEAD_LETTERED` и `False` для `RETRY_SCHEDULED`.

#### Scenario: Статистика
- **WHEN** есть одно задание в `RETRY_SCHEDULED` и одно в `DEAD_LETTERED`
- **THEN** `stats()` содержит ключи `retry_scheduled` и `dead_lettered` со значением 1, `list_jobs` по каждому статусу возвращает соответствующее задание

#### Scenario: Признак завершённости
- **WHEN** проверяется `is_terminal`
- **THEN** для `DEAD_LETTERED` — `True`, для `RETRY_SCHEDULED` — `False`

### Requirement: Отмена
`cancel()` SHALL работать для задания в `RETRY_SCHEDULED`: оно больше не выполняется, `jobs.cancelled` +1. Для задания в `DEAD_LETTERED` SHALL выбрасываться `InvalidTransitionError`.

#### Scenario: Отмена ожидающего повтора
- **WHEN** отменяется задание в `RETRY_SCHEDULED` и часы продвинуты за `run_at`
- **THEN** статус `CANCELLED`, воркер его не берёт

#### Scenario: Отмена задания из dead-letter
- **WHEN** отменяется задание в `DEAD_LETTERED`
- **THEN** `InvalidTransitionError`, задание остаётся в dead-letter

### Requirement: Очистка не затрагивает dead-letter
`purge_finished()` SHALL не удалять задания в `DEAD_LETTERED`: они остаются, пока их не перезапустят. Прочие завершённые задания SHALL удаляться как раньше.

#### Scenario: Purge
- **WHEN** есть `SUCCEEDED` и `DEAD_LETTERED` задания старше порога и вызывается `purge_finished()`
- **THEN** удаляется только `SUCCEEDED`; `dead_letters()` и `list_jobs(DEAD_LETTERED)` не изменились

### Requirement: Отчёт дежурных
`render_report` SHALL показывать новые статусы с подписями «Ожидает повтора» и «В dead-letter» и их количеством, без изменения кода отчёта.

#### Scenario: Строки отчёта
- **WHEN** строится отчёт при наличии заданий в новых статусах
- **THEN** в блоке статусов есть строки с этими подписями и верными числами, «Всего» учитывает их
