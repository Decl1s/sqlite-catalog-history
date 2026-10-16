import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from catalog_history import pipeline
from catalog_history.pipeline import HEADER, PipelineError, as_of, load, snapshots
from catalog_history.synthetic import generate


def product(code="P-0001", name="Чай", category="Напитки", price=100):
    return (code, name, category, price)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.input = self.root / "input"
        self.input.mkdir()
        self.db = self.root / "catalog.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, day, rows, header=HEADER):
        path = self.input / f"catalog-{day}.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def state(self):
        with sqlite3.connect(self.db) as connection:
            return {table: connection.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
                    for table in ("batches", "dim_product")}

    def test_demo_counts_and_boundary_dates(self):
        generate(self.input)
        result = load(self.input, self.db)
        self.assertEqual(result, {"loaded_snapshots": 3, "skipped_snapshots": 0, "created_versions": 9,
                                 "closed_versions": 4, "changed_products": 3, "missing_products": 1,
                                 "total_versions": 9, "current_products": 5})
        self.assertEqual(as_of(self.db, "2026-10-04")[0]["price_cents"], 25000)
        self.assertEqual(as_of(self.db, "2026-10-05")[0]["price_cents"], 27500)
        self.assertEqual(len(as_of(self.db, "2026-10-09")), 3)
        self.assertEqual(len(as_of(self.db, "2026-10-10")), 5)
        self.assertEqual(as_of(self.db, "2026-09-30"), [])

    def test_repeat_preserves_surrogate_keys_and_history(self):
        generate(self.input)
        load(self.input, self.db)
        before = self.state()
        result = load(self.input, self.db)
        self.assertEqual(result["skipped_snapshots"], 3)
        self.assertEqual(result["created_versions"], 0)
        self.assertEqual(self.state(), before)

    def test_unchanged_snapshot_has_checkpoint_but_no_new_version(self):
        self.write("2026-01-01", [product()])
        self.write("2026-01-03", [product()])
        result = load(self.input, self.db)
        self.assertEqual((result["total_versions"], result["loaded_snapshots"]), (1, 2))
        self.assertEqual(as_of(self.db, "2026-01-03")[0]["valid_from"], "2026-01-01")

    def test_missing_product_and_reappearance_create_gap(self):
        self.write("2026-01-01", [product()])
        self.write("2026-01-02", [])
        self.write("2026-01-04", [product()])
        load(self.input, self.db)
        self.assertEqual(as_of(self.db, "2026-01-02"), [])
        self.assertEqual(as_of(self.db, "2026-01-03"), [])
        rows = self.state()["dim_product"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][-1], "2026-01-02")
        self.assertIsNone(rows[1][-1])

    def test_late_new_snapshot_is_rejected(self):
        self.write("2026-01-03", [product()])
        load(self.input, self.db)
        before = self.state()
        self.write("2026-01-02", [product(price=200)])
        with self.assertRaisesRegex(PipelineError, "старше"):
            load(self.input, self.db)
        self.assertEqual(self.state(), before)

    def test_changed_loaded_bytes_are_rejected(self):
        path = self.write("2026-01-01", [product()])
        load(self.input, self.db)
        before = self.state()
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(PipelineError, "изменён"):
            load(self.input, self.db)
        self.assertEqual(self.state(), before)

    def test_failure_after_second_apply_rolls_back_all_new_snapshots(self):
        self.write("2026-01-01", [product()])
        load(self.input, self.db)
        before = self.state()
        self.write("2026-01-02", [product(price=200)])
        self.write("2026-01-03", [product(price=300)])
        original = pipeline._apply
        calls = 0

        def fail_after_write(connection, day, rows):
            nonlocal calls
            result = original(connection, day, rows)
            calls += 1
            if calls == 2:
                raise OSError("искусственный сбой")
            return result

        with patch.object(pipeline, "_apply", side_effect=fail_after_write):
            with self.assertRaises(OSError):
                load(self.input, self.db)
        self.assertEqual(self.state(), before)
        self.assertEqual(load(self.input, self.db)["total_versions"], 3)

    def test_failed_first_load_leaves_valid_empty_schema_for_retry(self):
        self.write("2026-01-01", [product()])
        with patch.object(pipeline, "_apply", side_effect=OSError("сбой")):
            with self.assertRaises(OSError):
                load(self.input, self.db)
        self.assertEqual(self.state(), {"batches": [], "dim_product": []})
        self.assertEqual(load(self.input, self.db)["total_versions"], 1)

    def test_invalid_rows_fail_before_database_creation(self):
        candidates = [[product(price=-1)], [product(), product()], [product(code="x")],
                      [product(name=" Чай")], [product(name="Чай\nещё")], [product(price="1.2")],
                      [product(price="001")], [product(price="١٢")], [product(price=100000001)],
                      [("P-0001", "Чай", "Напитки")], [product(category="")]]
        for rows in candidates:
            with self.subTest(rows=rows):
                self.write("2026-01-01", rows)
                with self.assertRaises(PipelineError):
                    load(self.input, self.db)
                self.assertFalse(self.db.exists())

    def test_wrong_header_encoding_and_broken_csv(self):
        path = self.write("2026-01-01", [], header=["other"])
        for content in (path.read_bytes(), b"\xff", b'product_id,name,category,price_cents\n"unfinished'):
            path.write_bytes(content)
            with self.assertRaises(PipelineError):
                load(self.input, self.db)

    def test_invalid_filename_date_and_size_limits(self):
        path = self.write("2026-02-30", [])
        with self.assertRaises(PipelineError):
            snapshots(self.input)
        path.rename(self.input / "unrecognized.csv")
        with self.assertRaises(PipelineError):
            snapshots(self.input)
        (self.input / "unrecognized.csv").unlink()
        self.write("2026-01-01", [product()])
        with patch.object(pipeline, "MAX_FILE_BYTES", 10):
            with self.assertRaises(PipelineError):
                snapshots(self.input)
        with patch.object(pipeline, "MAX_ROWS", 0):
            with self.assertRaises(PipelineError):
                snapshots(self.input)

    def test_foreign_database_is_not_modified(self):
        self.write("2026-01-01", [product()])
        with sqlite3.connect(self.db) as connection:
            connection.execute("CREATE TABLE important(value)")
            connection.execute("INSERT INTO important VALUES ('keep')")
        before = self.db.read_bytes()
        with self.assertRaisesRegex(PipelineError, "чужая"):
            load(self.input, self.db)
        self.assertEqual(self.db.read_bytes(), before)

    def test_database_cannot_be_under_input_directory(self):
        self.write("2026-01-01", [product()])
        with self.assertRaises(PipelineError):
            load(self.input, self.input / "history.sqlite3")

    def test_symlink_input_and_database_are_rejected(self):
        path = self.write("2026-01-01", [product()])
        target = self.root / "original.csv"
        path.rename(target)
        try:
            path.symlink_to(target)
        except OSError:
            self.skipTest("В этой среде нет прав на символические ссылки.")
        with self.assertRaises(PipelineError):
            load(self.input, self.db)
        path.unlink()
        target.rename(path)
        self.db.symlink_to(self.root / "elsewhere.sqlite3")
        with self.assertRaises(PipelineError):
            load(self.input, self.db)

    def test_sql_unique_open_and_interval_constraints(self):
        self.write("2026-01-01", [product()])
        load(self.input, self.db)
        with sqlite3.connect(self.db) as connection:
            connection.execute("INSERT INTO batches VALUES ('2026-01-02', ?, 1)", ("a" * 64,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO dim_product(product_id,name,category,price_cents,valid_from) VALUES (?,?,?,?,?)",
                                   (*product(), "2026-01-02"))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE dim_product SET valid_to=valid_from")

    def test_overlap_detected_before_further_mutation(self):
        self.write("2026-01-01", [product()])
        self.write("2026-01-02", [product(price=200)])
        self.write("2026-01-03", [product(price=300)])
        load(self.input, self.db)
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE dim_product SET valid_to='2026-01-03' WHERE valid_from='2026-01-01'")
        with self.assertRaisesRegex(PipelineError, "пересечение"):
            load(self.input, self.db)

    def test_as_of_is_read_only_and_rejects_unknown_future(self):
        self.write("2026-01-01", [product()])
        load(self.input, self.db)
        before = self.db.read_bytes()
        as_of(self.db, "2026-01-01")
        self.assertEqual(self.db.read_bytes(), before)
        for value in ("2026-01-02", "2026-02-30", "not-a-date"):
            with self.assertRaises(PipelineError):
                as_of(self.db, value)
        with self.assertRaises(PipelineError):
            as_of(self.root / "missing.sqlite3", "2026-01-01")

    def test_demo_is_deterministic_and_refuses_overwrite(self):
        generate(self.input)
        other = self.root / "other"
        generate(other)
        self.assertEqual([p.read_bytes() for p in sorted(self.input.glob("*.csv"))],
                         [p.read_bytes() for p in sorted(other.glob("*.csv"))])
        with self.assertRaises(PipelineError):
            generate(self.input)

    def test_cli_utf8_json_and_sanitized_error(self):
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        args = [sys.executable, "-m", "catalog_history"]
        result = subprocess.run(args + ["demo", "--input", str(self.input), "--json"], env=env, capture_output=True)
        self.assertEqual(json.loads(result.stdout)["input_rows"], 12)
        result = subprocess.run(args + ["load", "--input", str(self.input), "--db", str(self.db)], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertIn("Всего версий в истории: 9", result.stdout.decode("utf-8"))
        result = subprocess.run(args + ["as-of", "bad", "--db", str(self.db)], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(str(self.root), result.stderr.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
