"""Проверка стандартного демо через CLI, включая повтор и границы истории."""

import json
import subprocess
import sys


def command(*arguments):
    result = subprocess.run([sys.executable, "-m", "catalog_history", *arguments, "--json"],
                            check=True, capture_output=True, encoding="utf-8")
    return json.loads(result.stdout)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    repeat = command("load")
    assert repeat["loaded_snapshots"] == 0 and repeat["skipped_snapshots"] == 3
    assert repeat["total_versions"] == 9 and repeat["current_products"] == 5
    before, after, returned = (command("as-of", day) for day in ("2026-10-04", "2026-10-05", "2026-10-10"))
    assert before[0]["price_cents"] == 25000 and after[0]["price_cents"] == 27500
    assert "P-0003" not in {row["product_id"] for row in after}
    assert next(row for row in returned if row["product_id"] == "P-0003")["price_cents"] == 21000
    print("Демо проверено: 9 версий, 5 актуальных товаров, повтор без дублей и корректные границы дат.")


if __name__ == "__main__":
    main()
