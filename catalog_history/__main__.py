import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .pipeline import PipelineError, as_of, load
from .synthetic import generate


class RussianParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self.add_argument("-h", "--help", action="help", help="показать справку")

    def format_help(self):
        return super().format_help().replace("usage: ", "Использование: ").replace("options:", "Параметры:")

    def error(self, message):
        self.exit(2, "Ошибка параметров. Проверьте значения; справка: --help.\n")


LABELS = {"snapshots": "Создано снимков", "input_rows": "Синтетических строк",
          "expected_versions": "Ожидается версий", "expected_current": "Ожидается актуальных товаров",
          "loaded_snapshots": "Загружено снимков", "skipped_snapshots": "Пропущено прежних снимков",
          "created_versions": "Создано версий", "closed_versions": "Закрыто версий",
          "changed_products": "Изменений атрибутов", "missing_products": "Исчезновений товаров",
          "total_versions": "Всего версий в истории", "current_products": "Актуальных товаров"}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = RussianParser(prog="python -m catalog_history", description="История товаров SCD2 на SQLite")
    parser.add_argument("--version", action="version", version=__version__, help="показать версию")
    commands = parser.add_subparsers(dest="command", required=True, title="Команды")
    demo = commands.add_parser("demo", help="создать три синтетических снимка")
    demo.add_argument("--input", type=Path, default=Path("workspace/input"), help="пустая папка для демо")
    ingest = commands.add_parser("load", help="загрузить снимки одной транзакцией")
    ingest.add_argument("--input", type=Path, default=Path("workspace/input"), help="папка полных CSV-снимков")
    ingest.add_argument("--db", type=Path, default=Path("workspace/catalog.sqlite3"), help="файл базы истории")
    query = commands.add_parser("as-of", help="показать состояние на дату")
    query.add_argument("date", help="дата YYYY-MM-DD, не позже последнего снимка")
    query.add_argument("--db", type=Path, default=Path("workspace/catalog.sqlite3"), help="существующая база")
    for command in (demo, ingest, query):
        command.add_argument("--json", action="store_true", help="машинный вывод JSON")
    args = parser.parse_args()
    try:
        if args.command == "demo":
            result = generate(args.input)
        elif args.command == "load":
            result = load(args.input, args.db)
        else:
            result = as_of(args.db, args.date)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif isinstance(result, list):
            print(f"Состояние на {args.date}. Товаров: {len(result)}")
            for row in result:
                whole, fraction = divmod(row["price_cents"], 100)
                print(f'{row["product_id"]} · {row["name"]} · {row["category"]} · {whole},{fraction:02d} ₽')
        else:
            for key, value in result.items():
                print(f"{LABELS[key]}: {value}")
        return 0
    except (PipelineError, OSError, UnicodeError, sqlite3.Error) as exc:
        message = str(exc) if isinstance(exc, PipelineError) else "Не удалось прочитать вход или базу. Проверьте формат, права и блокировку файла."
        print("Ошибка: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
