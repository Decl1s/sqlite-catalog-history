# Фактические технологии

| Компонент | Версия | Назначение и выбор | Официальный источник |
| --- | --- | --- | --- |
| Python | Поддерживаемые 3.11–3.12; локально 3.12.3 | CLI, строгая проверка CSV, управление транзакцией | https://docs.python.org/3.12/ |
| SQLite | Локально 3.45.1; минимум 3.37.0 | Встроенная база, STRICT-таблицы, частичный индекс, транзакция | https://www.sqlite.org/docs.html |
| sqlite3 | Стандартная библиотека выбранного Python | Параметризованный SQL, read-only URI, явный BEGIN/COMMIT/ROLLBACK | https://docs.python.org/3.12/library/sqlite3.html |
| SQL | Диалект SQLite | Обновление интервалов, вставка версий и запрос на дату | https://www.sqlite.org/lang.html |
| CSV | UTF-8, разделитель запятая | Небольшой переносимый вход с жёстким контрактом | https://docs.python.org/3.12/library/csv.html |
| SHA-256 | hashlib стандартной библиотеки | Идентичность байтов снимка и контрольная сумма ZIP | https://docs.python.org/3.12/library/hashlib.html |
| unittest и unittest.mock | Стандартная библиотека | Границы интервалов, повторы, искусственный сбой и откат | https://docs.python.org/3.12/library/unittest.html |
| venv | Стандартная библиотека, без pip | Отдельное окружение без установки пакетов | https://docs.python.org/3.12/library/venv.html |
| ZIP, Markdown и JSON | Стандартные форматы | Исходный архив, русский конспект, машинный CLI | https://docs.python.org/3.12/library/zipfile.html |
| Git | 2.x | Изолированная история разработки, перечень публикуемых файлов | https://git-scm.com/docs |
| GitHub Actions | Ubuntu/Python 3.11, Ubuntu/Python 3.12, Windows/Python 3.12 | Тесты, демо и исходный архив на трёх средах | https://docs.github.com/ru/actions |
| actions/checkout | v4, SHA в ci.yml | Получение исходников без сохранения учётных данных | https://github.com/actions/checkout |
| actions/setup-python | v5, SHA в ci.yml | Установка выбранной версии Python | https://github.com/actions/setup-python |
| actions/upload-artifact | v4, SHA в ci.yml | Сохранение ZIP и контрольной суммы | https://github.com/actions/upload-artifact |

**Прямых и транзитивных сторонних runtime-зависимостей нет.** `requirements.txt`
фиксирует этот факт комментарием; установка через pip не требуется.
Версия SQLite определяется сборкой интерпретатора, не закрепляется requirements.txt.
Проверка минимальной версии встроена в загрузчик; CI печатает фактические версии.
Обновление Python может изменить SQLite: это нужно проверять, а не считать её версию постоянной.

Полный перечень используемых модулей стандартной библиотеки: argparse, contextlib,
csv, datetime, hashlib, importlib, io, json, os, pathlib, re, sqlite3, subprocess,
sys, tempfile, unittest и zipfile. Rust, Docker, Pandas, Polars и отдельный сервер
для этого проекта не нужны. Локальная обработка сеть не использует; публикация и CI используют GitHub.

Свойства SQLite, на которые опирается модель: [STRICT](https://www.sqlite.org/stricttables.html),
[частичные индексы](https://www.sqlite.org/partialindex.html),
[транзакции](https://www.sqlite.org/lang_transaction.html),
[внешние ключи](https://www.sqlite.org/foreignkeys.html).
