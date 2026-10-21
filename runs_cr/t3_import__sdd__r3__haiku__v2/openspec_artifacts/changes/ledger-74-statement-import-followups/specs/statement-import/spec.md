## MODIFIED Requirements

### Requirement: Sfera amounts and dates
Для формата `sfera` дата SHALL быть строго в виде `ДД.ММ.ГГГГ` и соответствовать реальной дате.
Сумма SHALL состоять из необязательного знака (`+` или `-`), цифр, где тысячи отделяются пробелом
или неразрывным пробелом (U+00A0), и необязательной дробной части из одного или двух знаков. Дробная
часть отделяется запятой или точкой; в одной сумме SHALL использоваться только один из двух
разделителей, сумма с обоими разделителями MUST быть ошибкой строки. Точка не является разделителем
тысяч: `1.234` — дробная часть из трёх знаков и ошибка. Приход без знака или со знаком `+`, расход со
знаком `-`. Дробная часть длиннее двух знаков SHALL быть ошибкой строки; сумма SHALL NOT округляться.

#### Scenario: Expense and income with thousands separators
- **WHEN** строки `01.03.2026;-1 200,50;Магазин Лента` и `02.03.2026;+85 000,00;Зарплата`, где пробел между тысячами неразрывный
- **THEN** импортируются транзакции `-1200.50` и `85000.00` с датами 2026-03-01 и 2026-03-02

#### Scenario: Dot as decimal separator
- **WHEN** сумма равна `-1 234.56`
- **THEN** импортируется транзакция `-1234.56`, строка не становится ошибкой

#### Scenario: Mixed decimal separators
- **WHEN** сумма равна `1,234.56` или `1.234,56`
- **THEN** строка становится ошибкой строки с `line_no` этой строки, и сумма не угадывается

#### Scenario: More than two decimal places
- **WHEN** сумма равна `-1,500` или `-1.500`
- **THEN** строка становится ошибкой, а не округляется до `-1.50`

#### Scenario: Invalid date format
- **WHEN** дата равна `2026-03-01` или `31.02.2026`
- **THEN** строка становится ошибкой строки

#### Scenario: Zero amount
- **WHEN** сумма равна `-0,00`
- **THEN** строка становится ошибкой, потому что нулевая транзакция недопустима

### Requirement: Sfera split amounts
Для формата `sfera_split` суммы в колонках `Приход` и `Расход` SHALL быть без знака, в том же
числовом формате, что и `sfera` (запятая или точка как разделитель дробной части). Заполнена ровно
одна из двух колонок: значение `Приход` даёт положительную сумму, значение `Расход` даёт отрицательную.
Знак в любой из колонок, обе заполненные колонки или ни одной заполненной колонки SHALL быть ошибкой
строки. Исключение — строка с явным нулём в обеих колонках: она SHALL пропускаться как служебная
(см. требование «Sfera service rows are skipped»). Значение `0,00` (или `0.00`) в одной колонке
SHALL считаться пустым.

#### Scenario: Expense goes negative
- **WHEN** строка `03.03.2026;Кофе;;150,00` (колонка `Приход` пуста, `Расход` равен `150,00`)
- **THEN** импортируется транзакция `-150.00`

#### Scenario: Dot in a split column
- **WHEN** строка `03.03.2026;Кофе;;150.00`
- **THEN** импортируется транзакция `-150.00`

#### Scenario: Zero in the unused column
- **WHEN** строка `03.03.2026;Зарплата;85 000,00;0,00`
- **THEN** импортируется транзакция `85000.00`, потому что `0,00` в `Расход` равно пустой колонке

#### Scenario: Zero in one column and empty in the other
- **WHEN** строка `03.03.2026;Кофе;0,00;`
- **THEN** строка становится ошибкой строки, потому что ни одна колонка не заполнена ненулевой суммой

#### Scenario: Both columns filled
- **WHEN** строка `03.03.2026;Странно;10,00;10,00`
- **THEN** строка становится ошибкой строки

#### Scenario: Sign in a split column
- **WHEN** строка `03.03.2026;Кофе;;-150,00`
- **THEN** строка становится ошибкой строки

### Requirement: Row errors do not stop a non-strict import
Если `strict` равен `False` (значение по умолчанию), ошибочная строка SHALL попасть в
`ImportResult.errors` как `RowError` с `line_no` по правилам `StatementError` (номер физической строки
файла, заголовок — строка 1), а остальные строки SHALL импортироваться. Ошибкой строки является
всё, из чего не собирается корректная `Transaction`, включая пустое описание, неверную дату,
неверную сумму и недостающие ячейки. `RowError.raw` SHALL содержать текст записи так, как он стоит в
файле: без BOM, без символов `\r` и без перевода строки в конце. Если запись занимает несколько строк
файла, они SHALL соединяться через `\n`.

#### Scenario: One broken row among valid rows
- **WHEN** в файле из трёх строк вторая строка содержит дату `2026-13-01`
- **THEN** `errors` содержит одну запись с `line_no` равным 3, а первая и третья строки добавляются

#### Scenario: Multi-line quoted record
- **WHEN** запись в кавычках занимает строки 4–5 и ошибочна
- **THEN** `RowError.line_no` равен 4, то есть строке, с которой запись начинается, а `RowError.raw` содержит две строки, соединённые через `\n`, без `\r`

#### Scenario: Raw text of a Windows line
- **WHEN** ошибочная строка заканчивается на `\r\n` в файле
- **THEN** `RowError.raw` не содержит `\r` и `\n` в конце

#### Scenario: Raw text of a file with BOM
- **WHEN** файл сохранён в UTF-8 с BOM, а первая строка данных ошибочна
- **THEN** `RowError.raw` не содержит символа BOM

### Requirement: Strict mode is atomic
Если `strict` равен `True`, импорт SHALL разобрать файл до конца и затем бросить `StatementRowError`.
`StatementRowError.errors` SHALL содержать все `RowError` файла в порядке строк, а `line_no` и
сообщение исключения SHALL браться у первой ошибки. В хранилище и в файл хранилища SHALL NOT попасть
никакие транзакции из файла. Дубли при этом ошибками не считаются.

#### Scenario: Error in the last line
- **WHEN** в файле 100 корректных строк и ошибка в строке 101, вызван `strict=True`
- **THEN** бросается `StatementRowError` с `line_no` равным 101, `errors` содержит одну запись, и `store.all()` не меняется

#### Scenario: Several errors in strict mode
- **WHEN** в файле ошибки в строках 3 и 7, вызван `strict=True`
- **THEN** бросается `StatementRowError` с `line_no` равным 3, `errors` содержит записи для строк 3 и 7 по порядку, и `store.all()` не меняется

#### Scenario: Duplicates in strict mode
- **WHEN** все строки файла уже есть в хранилище и вызван `strict=True`
- **THEN** импорт завершается без исключения, `duplicates` равен числу строк, `added` равен 0

### Requirement: Normalized description comparison
Описания при сравнении на дубли SHALL сравниваться через `normalize_description`, которая совпадает
с нормализацией, используемой в проекте для правил категоризации. Сохраняемое описание SHALL быть
обрезано по краям, а каждая последовательность пробельных символов внутри (пробелы, табы, переводы
строк, неразрывные пробелы) SHALL заменяться одним пробелом. Регистр и буквы SHALL NOT меняться.
Нормализация описания SHALL применяться ко всем форматам.

#### Scenario: Case, spacing and yo/ye differences
- **WHEN** в хранилище есть описание `  Кофейня   Зерно`, а в файле `кофейня зерно`
- **THEN** строка из файла считается дублем, если дата и сумма совпадают

#### Scenario: Stored description is not normalized
- **WHEN** импортируется строка с описанием `Магазин  Лента`
- **THEN** сохранённое описание равно `Магазин Лента`: пробелы схлопнуты, но регистр и буквы не изменены и полная нормализация для сравнения не применяется

#### Scenario: Stored description keeps case and collapses line breaks
- **WHEN** импортируется запись с описанием `  кофе\n  ЗЁРНА\tотличное  `
- **THEN** сохранённое описание равно `кофе ЗЁРНА отличное`

### Requirement: Sfera service rows are skipped
Строка формата `sfera_split`, в которой обе колонки суммы содержат явный ноль без знака (`0`, `0,00`,
`0.00` и т.п.), SHALL пропускаться без следа: она SHALL NOT попадать в `errors`, `duplicates` или
`added` и SHALL NOT создавать транзакцию. Знак, пустая колонка рядом с нулём или дробная часть
длиннее двух знаков SHALL NOT делать строку служебной: такие строки остаются ошибками строки.

#### Scenario: Blocking operation with zeros in both columns
- **WHEN** строка `03.03.2026;Блокировка;0,00;0,00`
- **THEN** строка пропускается, `errors` не содержит её, `added` и `duplicates` не меняются

#### Scenario: Zeros with a dot in both columns
- **WHEN** строка `03.03.2026;Блокировка;0.00;0.00`
- **THEN** строка пропускается так же, как с запятой

#### Scenario: Signed zeros are not service rows
- **WHEN** строка `03.03.2026;Блокировка;-0,00;0,00`
- **THEN** строка становится ошибкой строки

#### Scenario: Zero with excess decimal places is not a service row
- **WHEN** строка `03.03.2026;Блокировка;0,000;0,00`
- **THEN** строка становится ошибкой строки

## ADDED Requirements

### Requirement: Dry run preview
Если вызван `import_statement` с `dry_run=True`, импорт SHALL выполнить те же разбор, проверку
строк, дедупликацию, категоризацию и подсчёт, что и обычный импорт того же файла. Импорт SHALL NOT
записывать ничего в хранилище: `store.add_many` не вызывается, файл хранилища не меняется. Поля
`ImportResult` (`added`, `duplicates`, `errors`, `transactions`) SHALL совпадать с результатом
настоящего импорта при том же состоянии хранилища; у транзакций превью `id` SHALL быть `None`.
Параметр `strict` в превью SHALL действовать так же: при ошибке строки бросается `StatementRowError`.

#### Scenario: Preview leaves the JSON store unchanged
- **WHEN** вызван `import_statement(path, store, dry_run=True)` с `JsonFileStore` и в файле есть новые строки
- **THEN** байты файла хранилища не меняются, а `ImportResult.added` равен числу строк, которые добавил бы настоящий импорт

#### Scenario: Preview matches the real import
- **WHEN** превью выполнено, а затем вызван обычный импорт того же файла
- **THEN** `added`, `duplicates`, `errors` и даты/суммы в `transactions` совпадают, а в хранилище появляются только транзакции настоящего импорта

#### Scenario: Preview transactions have no ids
- **WHEN** вызван `import_statement(path, store, dry_run=True)` и файл содержит две новые строки
- **THEN** `ImportResult.transactions` содержит две транзакции с `id` равным `None` в порядке строк файла

#### Scenario: Preview in strict mode with an error
- **WHEN** вызван `import_statement(path, store, dry_run=True, strict=True)` и в файле есть ошибка строки
- **THEN** бросается `StatementRowError`, и хранилище не меняется

### Requirement: Imported transactions in the result
`ImportResult.transactions` SHALL содержать добавленные транзакции в порядке строк файла. При обычном
импорте каждая транзакция SHALL иметь `id`, назначенный хранилищем. Дубли и строки с ошибками в список
SHALL NOT попадать. Если добавлений нет, список SHALL быть пустым.

#### Scenario: Added transactions in file order with store ids
- **WHEN** в хранилище пусто, а файл содержит строки `01.03.2026;-5,00;A` и `02.03.2026;-6,00;B`
- **THEN** `ImportResult.transactions` содержит транзакции `A` и `B` в этом порядке, с `id` от хранилища

#### Scenario: Duplicates are not in the list
- **WHEN** первая строка файла уже есть в хранилище, а вторая новая
- **THEN** `ImportResult.transactions` содержит только вторую транзакцию

#### Scenario: Empty list when nothing is added
- **WHEN** все строки файла — дубли
- **THEN** `ImportResult.transactions` равен пустому списку
