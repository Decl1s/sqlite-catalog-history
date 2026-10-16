"""Три небольших полных снимка; никакие личные источники не читаются."""

import csv
from pathlib import Path

from .pipeline import HEADER, PipelineError, no_symlinks


def generate(directory):
    directory = Path(directory).absolute()
    no_symlinks(directory)
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise PipelineError("Для демо нужна пустая папка. Существующие файлы не заменяются.")
    directory.mkdir(parents=True, exist_ok=True)
    first = [("P-0001", "Чай", "Напитки", 25000), ("P-0002", "Кружка", "Посуда", 45000),
             ("P-0003", "Блокнот", "Канцелярия", 18000), ("P-0004", "Карандаш", "Канцелярия", 5000)]
    second = [(*first[0][:3], 27500), first[1], ("P-0004", "Карандаш", "Для школы", 5000)]
    third = [second[0], ("P-0002", "Кружка", "Подарки", 45000),
             ("P-0003", "Блокнот", "Канцелярия", 21000), second[2], ("P-0005", "Папка", "Канцелярия", 9900)]
    for day, rows in zip(("2026-10-01", "2026-10-05", "2026-10-10"), (first, second, third)):
        with (directory / f"catalog-{day}.csv").open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(HEADER)
            writer.writerows(rows)
    return {"snapshots": 3, "input_rows": 12, "expected_versions": 9, "expected_current": 5}
