"""CSV полного снимка → проверка → одна транзакция SQLite → история SCD2."""

import csv
import hashlib
import io
import re
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

APP_ID = 0x53434432
SCHEMA_VERSION = 1
HEADER = ["product_id", "name", "category", "price_cents"]
MAX_FILES, MAX_ROWS, MAX_FILE_BYTES = 30, 10_000, 2 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
SQL = Path(__file__).parent / "sql"


class PipelineError(ValueError):
    pass


def sql(name):
    return (SQL / name).read_text(encoding="utf-8")


def checked_date(value):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise PipelineError("Дата должна иметь формат YYYY-MM-DD.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise PipelineError("Указана несуществующая календарная дата.") from None
    return value


def no_symlinks(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise PipelineError("Символические ссылки в путях не поддерживаются.")


def snapshots(directory):
    directory = Path(directory).absolute()
    no_symlinks(directory)
    if not directory.is_dir():
        raise PipelineError("Папка входных снимков не найдена.")
    paths = sorted(directory.glob("*.csv"))
    if not 1 <= len(paths) <= MAX_FILES:
        raise PipelineError("Нужны от 1 до 30 CSV-снимков.")
    result, total = [], 0
    for path in paths:
        no_symlinks(path)
        match = re.fullmatch(r"catalog-([0-9]{4}-[0-9]{2}-[0-9]{2})\.csv", path.name)
        if not match or not path.is_file():
            raise PipelineError("Имя снимка должно быть catalog-YYYY-MM-DD.csv.")
        snapshot_date = checked_date(match[1])
        with path.open("rb") as stream:
            content = stream.read(MAX_FILE_BYTES + 1)
        total += len(content)
        if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise PipelineError("Превышен предел размера входных данных.")
        try:
            reader = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
            if next(reader, None) != HEADER:
                raise PipelineError("Заголовок CSV не соответствует контракту.")
            rows, seen = [], set()
            for number, values in enumerate(reader, 2):
                if len(rows) >= MAX_ROWS:
                    raise PipelineError("Снимок содержит больше 10 000 товаров.")
                if len(values) != 4:
                    raise PipelineError(f"Строка {number}: требуется ровно четыре поля.")
                product_id, name, category, price = values
                if not re.fullmatch(r"P-[0-9]{4}", product_id) or product_id in seen:
                    raise PipelineError(f"Строка {number}: неверный или повторяющийся код товара.")
                if any(not 1 <= len(v) <= 80 or v != v.strip()
                       or any(ord(c) < 32 or ord(c) == 127 for c in v) for v in (name, category)):
                    raise PipelineError(f"Строка {number}: неверное название или категория.")
                if not re.fullmatch(r"0|[1-9][0-9]{0,8}", price) or int(price) > 100_000_000:
                    raise PipelineError(f"Строка {number}: цена должна быть целым числом копеек.")
                seen.add(product_id)
                rows.append((product_id, name, category, int(price)))
        except (UnicodeError, csv.Error):
            raise PipelineError("Не удалось прочитать корректный CSV в UTF-8.") from None
        result.append((snapshot_date, hashlib.sha256(content).hexdigest(), rows))
    return result


def verify_database(connection):
    if (connection.execute("PRAGMA application_id").fetchone()[0] != APP_ID
            or connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION):
        raise PipelineError("Это чужая база или неподдерживаемая версия схемы.")
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    if tables != {"batches", "dim_product"}:
        raise PipelineError("Состав таблиц базы отличается от схемы проекта.")


def validate_history(connection):
    # Проверяем весь инвариант, включая закрытые интервалы, а не только открытые строки.
    overlap = connection.execute("""
        SELECT 1 FROM dim_product a JOIN dim_product b
        ON a.product_id=b.product_id AND a.product_version_id < b.product_version_id
        WHERE a.valid_from < COALESCE(b.valid_to, '9999-12-31')
          AND b.valid_from < COALESCE(a.valid_to, '9999-12-31') LIMIT 1
    """).fetchone()
    if overlap or connection.execute("PRAGMA foreign_key_check").fetchone():
        raise PipelineError("Нарушена целостность истории: пересечение интервалов или ссылка.")


def _apply(connection, snapshot_date, rows):
    connection.execute("DELETE FROM stage")
    connection.executemany("INSERT INTO stage VALUES (?, ?, ?, ?)", rows)
    changed = connection.execute("""SELECT count(*) FROM current_products c JOIN stage s USING(product_id)
        WHERE c.name<>s.name OR c.category<>s.category OR c.price_cents<>s.price_cents""").fetchone()[0]
    missing = connection.execute("""SELECT count(*) FROM current_products c
        WHERE NOT EXISTS (SELECT 1 FROM stage s WHERE s.product_id=c.product_id)""").fetchone()[0]
    # executescript сделал бы неявный COMMIT; выполняем две известные команды отдельно.
    statements = sql("apply_snapshot.sql").split(";")
    connection.execute(statements[0], {"snapshot_date": snapshot_date})
    closed = connection.execute("SELECT changes()").fetchone()[0]
    connection.execute(statements[1], {"snapshot_date": snapshot_date})
    created = connection.execute("SELECT changes()").fetchone()[0]
    return {"created_versions": created, "closed_versions": closed,
            "changed_products": changed, "missing_products": missing}


def load(directory, database):
    if sqlite3.sqlite_version_info < (3, 37, 0):
        raise PipelineError("Требуется SQLite 3.37 или новее для STRICT-таблиц.")
    directory, database = Path(directory).absolute(), Path(database).absolute()
    no_symlinks(database)
    if database.resolve().is_relative_to(directory.resolve()):
        raise PipelineError("База должна находиться вне входной папки.")
    inputs = snapshots(directory)  # Всё проверяем до создания базы и до изменения состояния.
    existed = database.exists()
    if existed and (not database.is_file() or database.stat().st_size > 256 * 1024 * 1024):
        raise PipelineError("База недоступна или превышает учебный предел 256 МиБ.")
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, isolation_level=None, timeout=5)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        if not existed:
            # Пустая схема остаётся пригодной для повтора при сбое первой поставки.
            connection.executescript("BEGIN IMMEDIATE;\n" + sql("schema.sql")
                                     + f"\nPRAGMA application_id={APP_ID}; PRAGMA user_version=1; COMMIT;")
        verify_database(connection)
        result = {"loaded_snapshots": 0, "skipped_snapshots": 0, "created_versions": 0,
                  "closed_versions": 0, "changed_products": 0, "missing_products": 0}
        connection.execute("BEGIN IMMEDIATE")
        try:
            validate_history(connection)
            known = dict(connection.execute("SELECT snapshot_date, source_sha256 FROM batches"))
            latest = max(known, default="")
            connection.execute("CREATE TEMP TABLE stage(product_id TEXT PRIMARY KEY, name TEXT, category TEXT, price_cents INTEGER)")
            for snapshot_date, digest, rows in inputs:
                if snapshot_date in known:
                    if known[snapshot_date] != digest:
                        raise PipelineError("Уже загруженный снимок изменён. История не переписывается.")
                    result["skipped_snapshots"] += 1
                    continue
                if snapshot_date <= latest:
                    raise PipelineError("Новый снимок старше последней загрузки. Нужна отдельная пересборка истории.")
                connection.execute("INSERT INTO batches VALUES (?, ?, ?)", (snapshot_date, digest, len(rows)))
                counters = _apply(connection, snapshot_date, rows)
                for key, value in counters.items():
                    result[key] += value
                result["loaded_snapshots"] += 1
                latest = snapshot_date
            validate_history(connection)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        result["total_versions"] = connection.execute("SELECT count(*) FROM dim_product").fetchone()[0]
        result["current_products"] = connection.execute("SELECT count(*) FROM current_products").fetchone()[0]
        return result


def as_of(database, value):
    value = checked_date(value)
    database = Path(database).absolute()
    no_symlinks(database)
    if not database.is_file():
        raise PipelineError("База истории не найдена. Сначала выполните load.")
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        verify_database(connection)
        latest = connection.execute("SELECT max(snapshot_date) FROM batches").fetchone()[0]
        if latest is None or value > latest:
            raise PipelineError("На эту дату нет подтверждённого снимка: запрос позже последней загрузки.")
        validate_history(connection)
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql("as_of.sql"), {"as_of": value})]
