from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from mergecsv.dialect import SourceDialect, parse_csv
from mergecsv.headers import normalize_header
from mergecsv.merge import merge_csv
from mergecsv.numbers import NumberParseError, parse_numeric


REPO_ROOT = Path(__file__).resolve().parents[1]


EXPECTED_CONFIG = {
    "sources": {
        "shop_a": {
            "delimiter": ",",
            "escape": "doubling",
            "nulls": ["", "NULL"],
            "encoding": "utf-8-sig",
        },
        "shop_b": {
            "delimiter": ",",
            "escape": "doubling",
            "nulls": [""],
            "encoding": "utf-8",
        },
        "shop_c": {
            "delimiter": ";",
            "escape": "backslash",
            "nulls": ["", "NULL", r"\N"],
            "encoding": "utf-8",
        },
    },
    "columns": {
        "order_id": {
            "type": "text",
            "aliases": ["order_id", "订单号"],
            "primary": "shop_a",
        },
        "price": {
            "type": "money",
            "aliases": ["price", "成交价"],
            "primary": "shop_a",
        },
        "tax_rate": {
            "type": "rate",
            "aliases": ["tax_rate", "税率"],
            "primary": "shop_a",
        },
        "remark": {
            "type": "text",
            "aliases": ["remark", "notes", "备注"],
            "primary": "shop_a",
        },
    },
}


def write_fixtures(base_dir: Path, config: dict | None = None) -> tuple[Path, Path]:
    sources_dir = base_dir / "sources"
    sources_dir.mkdir()
    aliases_path = base_dir / "aliases.json"
    aliases_path.write_text(
        json.dumps(config or EXPECTED_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    bom = b"\xef\xbb\xbf"
    (sources_dir / "shop_a.csv").write_bytes(
        bom
        + (
            "order_id,price,tax_rate,remark\r\n"
            'A1,"1,234.50",0.08,ok\r\n'
            "B1,120.00,0.08,keep\r\n"
            "C1,50.00,0.08,ok\r\n"
            "D1,70.00,0.08,ok\r\n"
            "F1,N/A,0.08,NULL\r\n"
        ).encode("utf-8")
    )
    (sources_dir / "shop_b.csv").write_bytes(
        bom
        + (
            "order_id,price,tax_rate,remark,notes\n"
            'A1,"1,234.50",8%,ok,note-a\n'
            "B1,125.00,0.08,keep,note-b\n"
            "C1,50.00,0.08,ok,note-c\n"
            "D1,70.00,0.08,,note-d\n"
            "F1,50.00,0.08,ok,note-f\n"
        ).encode("utf-8")
    )
    (sources_dir / "shop_c.csv").write_bytes(
        (
            "order_id;成交价;税率;备注\r\n"
            "A1;1234.50;8,5%;ok\r\n"
            r"C1;\N;0.08;ok" + "\r\n"
            "D1;70.00;0.08;ok\r\n"
            r'E1;42.00;0.08;"say \"hi\""' + "\r\n"
        ).encode("utf-8")
    )
    return sources_dir, aliases_path


class MergeFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base_dir = Path(self.temp_dir.name)
        self.sources_dir, self.aliases_path = write_fixtures(base_dir)
        self.report = merge_csv(self.sources_dir, self.aliases_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def row(self, order_id: str) -> dict:
        rows = {row["order_id"]: row for row in self.report["rows"]}
        return rows[order_id]

    def conflict(self, order_id: str, column: str) -> dict:
        matches = [
            item
            for item in self.report["conflicts"]
            if item["order_id"] == order_id and item["column"] == column
        ]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_01_demo_config_and_source_files_match_required_fixture(self) -> None:
        config_path = REPO_ROOT / "demo" / "aliases.json"
        self.assertEqual(json.loads(config_path.read_text(encoding="utf-8")), EXPECTED_CONFIG)

        shop_a = (REPO_ROOT / "demo" / "sources" / "shop_a.csv").read_bytes()
        shop_b = (REPO_ROOT / "demo" / "sources" / "shop_b.csv").read_bytes()
        shop_c = (REPO_ROOT / "demo" / "sources" / "shop_c.csv").read_bytes()
        self.assertTrue(shop_a.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(shop_b.startswith(b"\xef\xbb\xbf"))
        self.assertFalse(shop_c.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", shop_a)
        self.assertNotIn(b"\n", shop_a.replace(b"\r\n", b""))
        self.assertIn(b"\n", shop_b)
        self.assertNotIn(b"\r", shop_b)
        self.assertIn(b"\r\n", shop_c)
        self.assertIn(b"order_id;\xe6\x88\x90\xe4\xba\xa4\xe4\xbb\xb7;", shop_c)

    def test_02_six_rows_sorted_by_order_id(self) -> None:
        self.assertEqual(
            [row["order_id"] for row in self.report["rows"]],
            ["A1", "B1", "C1", "D1", "E1", "F1"],
        )

    def test_03_a1_price_equivalent_values_have_no_conflict(self) -> None:
        self.assertEqual(self.row("A1")["price"], "1234.50")
        self.assertFalse(
            any(
                item["order_id"] == "A1" and item["column"] == "price"
                for item in self.report["conflicts"]
            )
        )

    def test_04_a1_tax_rate_percent_and_conflict(self) -> None:
        self.assertEqual(self.row("A1")["tax_rate"], "0.08")
        self.assertEqual(
            self.conflict("A1", "tax_rate"),
            {
                "order_id": "A1",
                "column": "tax_rate",
                "kept_value": "0.08",
                "kept_source": "shop_a",
                "dropped_value": "0.085",
                "dropped_source": "shop_c",
            },
        )

    def test_05_conflict_list_contains_exactly_two_expected_conflicts(self) -> None:
        self.assertEqual(
            sorted(
                (item["order_id"], item["column"])
                for item in self.report["conflicts"]
            ),
            [("A1", "tax_rate"), ("B1", "price")],
        )
        self.assertEqual(
            self.conflict("B1", "price"),
            {
                "order_id": "B1",
                "column": "price",
                "kept_value": "120.00",
                "kept_source": "shop_a",
                "dropped_value": "125.00",
                "dropped_source": "shop_b",
            },
        )

    def test_06_c1_null_does_not_conflict_but_source_still_appears(self) -> None:
        self.assertEqual(self.row("C1")["price"], "50.00")
        self.assertEqual(self.row("C1")["sources"], ["shop_a", "shop_b", "shop_c"])
        self.assertFalse(
            any(
                item["order_id"] == "C1" and item["column"] == "price"
                for item in self.report["conflicts"]
            )
        )

    def test_07_f1_type_error_and_lexicographic_fallback(self) -> None:
        self.assertEqual(
            self.report["type_errors"],
            [
                {
                    "source": "shop_a",
                    "order_id": "F1",
                    "column": "price",
                    "raw": "N/A",
                }
            ],
        )
        self.assertEqual(self.row("F1")["price"], "50.00")
        self.assertEqual(self.row("F1")["sources"], ["shop_a", "shop_b"])

    def test_08_alias_conflict_invalidates_remark_in_shop_b(self) -> None:
        self.assertEqual(
            self.report["alias_conflicts"],
            [{"source": "shop_b", "column": "remark", "header": "notes"}],
        )
        self.assertEqual(self.row("B1")["remark"], "keep")
        self.assertIsNone(self.row("F1")["remark"])

    def test_09_shop_c_backslash_escaped_quote_and_sources(self) -> None:
        self.assertEqual(self.row("E1")["remark"], 'say "hi"')
        self.assertEqual(self.row("E1")["sources"], ["shop_c"])

    def test_10_bom_and_alias_headers_are_normalized(self) -> None:
        self.assertEqual(normalize_header("\ufeff order_id "), "order id")
        self.assertEqual(normalize_header(" Tax\u00a0Rate "), "tax rate")
        self.assertEqual(normalize_header("全角\u3000备注"), "全角 备注")
        demo_report = merge_csv(
            REPO_ROOT / "demo" / "sources",
            REPO_ROOT / "demo" / "aliases.json",
        )
        self.assertEqual(demo_report["rows"][0]["order_id"], "A1")

    def test_11_aliases_used_shape_sorting_and_matched_sources(self) -> None:
        self.assertEqual(
            [item["unified"] for item in self.report["aliases_used"]],
            ["order_id", "price", "remark", "tax_rate"],
        )
        self.assertEqual(self.report["aliases_used"][2]["matched_sources"], ["shop_a", "shop_c"])
        for item in self.report["aliases_used"]:
            self.assertEqual(list(item.keys()), ["unified", "primary", "matched_sources"])

    def test_12_report_shapes_and_summary(self) -> None:
        self.assertEqual(
            list(self.report.keys()),
            ["rows", "conflicts", "type_errors", "alias_conflicts", "summary", "aliases_used"],
        )
        for row in self.report["rows"]:
            self.assertEqual(
                list(row.keys()),
                ["order_id", "price", "tax_rate", "remark", "sources"],
            )
        for conflict in self.report["conflicts"]:
            self.assertEqual(
                list(conflict.keys()),
                [
                    "order_id",
                    "column",
                    "kept_value",
                    "kept_source",
                    "dropped_value",
                    "dropped_source",
                ],
            )
        for type_error in self.report["type_errors"]:
            self.assertEqual(list(type_error.keys()), ["source", "order_id", "column", "raw"])
        for alias_conflict in self.report["alias_conflicts"]:
            self.assertEqual(list(alias_conflict.keys()), ["source", "column", "header"])
        self.assertEqual(
            self.report["summary"],
            {"rows": 6, "conflicts": 2, "type_errors": 1, "alias_conflicts": 1, "sources": 3},
        )

    def test_13_numeric_rendering_uses_exact_decimal_strings(self) -> None:
        self.assertEqual(self.row("B1")["price"], "120.00")
        self.assertEqual(self.row("C1")["price"], "50.00")
        self.assertEqual(self.row("E1")["price"], "42.00")
        self.assertEqual(self.row("A1")["tax_rate"], "0.08")
        self.assertEqual(self.conflict("A1", "tax_rate")["dropped_value"], "0.085")
        rendered = json.dumps(self.report, ensure_ascii=False)
        self.assertNotIn("1,234.50", rendered)
        self.assertNotIn("0.080000", rendered)

    def test_14_changing_primary_source_changes_kept_side(self) -> None:
        with tempfile.TemporaryDirectory() as other_dir_name:
            other_dir = Path(other_dir_name)
            changed_config = json.loads(json.dumps(EXPECTED_CONFIG))
            changed_config["columns"]["price"]["primary"] = "shop_b"
            sources_dir, aliases_path = write_fixtures(other_dir, changed_config)
            report = merge_csv(sources_dir, aliases_path)

        conflict = next(
            item
            for item in report["conflicts"]
            if item["order_id"] == "B1" and item["column"] == "price"
        )
        self.assertEqual(conflict["kept_value"], "125.00")
        self.assertEqual(conflict["kept_source"], "shop_b")
        self.assertEqual(conflict["dropped_value"], "120.00")
        self.assertEqual(conflict["dropped_source"], "shop_a")
        self.assertEqual(report["summary"], {"rows": 6, "conflicts": 2, "type_errors": 1, "alias_conflicts": 1, "sources": 3})

    def test_15_changing_shop_c_rate_removes_one_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as other_dir_name:
            other_dir = Path(other_dir_name)
            sources_dir, aliases_path = write_fixtures(other_dir)
            shop_c = sources_dir / "shop_c.csv"
            shop_c.write_bytes(shop_c.read_bytes().replace("8,5%".encode(), "8,0%".encode()))
            report = merge_csv(sources_dir, aliases_path)

        rows = {row["order_id"]: row for row in report["rows"]}
        self.assertEqual(rows["A1"]["tax_rate"], "0.08")
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(
            report["conflicts"][0],
            {
                "order_id": "B1",
                "column": "price",
                "kept_value": "120.00",
                "kept_source": "shop_a",
                "dropped_value": "125.00",
                "dropped_source": "shop_b",
            },
        )
        self.assertEqual(report["summary"]["rows"], 6)
        self.assertEqual(report["summary"]["type_errors"], 1)
        self.assertEqual(report["summary"]["alias_conflicts"], 1)


class DialectAndNumberTests(unittest.TestCase):
    def test_order_id_keeps_leading_zeroes_and_is_case_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as dir_name:
            base_dir = Path(dir_name)
            sources_dir, aliases_path = write_fixtures(base_dir)
            (sources_dir / "shop_b.csv").write_text(
                "order_id,price,tax_rate,remark,notes\n", encoding="utf-8"
            )
            (sources_dir / "shop_c.csv").write_text(
                "order_id;成交价;税率;备注\r\n", encoding="utf-8"
            )
            (sources_dir / "shop_a.csv").write_text(
                "order_id,price,tax_rate,remark\r\n"
                "007,1.00,0.01,a\r\n"
                "7,2.00,0.02,b\r\n"
                "ab,3.00,0.03,c\r\n"
                "AB,4.00,0.04,d\r\n",
                encoding="utf-8",
            )
            report = merge_csv(sources_dir, aliases_path)

        self.assertEqual([row["order_id"] for row in report["rows"]], ["007", "7", "AB", "ab"])

    def test_csv_escaping_line_endings_and_unquoted_backslash(self) -> None:
        doubling = SourceDialect(",", "doubling", (), "utf-8")
        backslash = SourceDialect(";", "backslash", (), "utf-8")

        self.assertEqual(
            parse_csv('a,"q""x"\r\nb,c\n', doubling),
            [["a", 'q"x'], ["b", "c"]],
        )
        self.assertEqual(
            parse_csv(r'a\b;"c\\d";"say \"hi\""' + "\r\n", backslash),
            [[r"a\b", r"c\d", 'say "hi"']],
        )

    def test_numeric_separators_currency_negative_percent_and_rounding(self) -> None:
        self.assertEqual(parse_numeric("1.234,56", "money"), Decimal("1234.56"))
        self.assertEqual(parse_numeric("1,234.56", "money"), Decimal("1234.56"))
        self.assertEqual(parse_numeric("1,234", "money"), Decimal("1234.00"))
        self.assertEqual(parse_numeric("1.234", "money"), Decimal("1234.00"))
        self.assertEqual(parse_numeric("1,2", "money"), Decimal("1.20"))
        self.assertEqual(parse_numeric("USD 50-", "money"), Decimal("-50.00"))
        self.assertEqual(parse_numeric("(€12.34)", "money"), Decimal("-12.34"))
        self.assertEqual(parse_numeric("8,5%", "rate"), Decimal("0.085000"))
        self.assertEqual(parse_numeric("1.005", "money"), Decimal("1005.00"))
        self.assertEqual(parse_numeric("1.0055", "money"), Decimal("1.01"))
        self.assertEqual(parse_numeric("0.1234567", "rate"), Decimal("0.123457"))
        with self.assertRaises(NumberParseError):
            parse_numeric("N/A", "money")
        with self.assertRaises(NumberParseError):
            parse_numeric("8%", "money")


class DeterminismAndCliTests(unittest.TestCase):
    def test_same_input_produces_byte_identical_report(self) -> None:
        with tempfile.TemporaryDirectory() as dir_name:
            base_dir = Path(dir_name)
            sources_dir, aliases_path = write_fixtures(base_dir)
            first = json.dumps(merge_csv(sources_dir, aliases_path), ensure_ascii=False, indent=2).encode("utf-8")
            second = json.dumps(merge_csv(sources_dir, aliases_path), ensure_ascii=False, indent=2).encode("utf-8")
            self.assertEqual(first, second)

    def test_demo_cli_writes_report_and_prints_one_summary_line(self) -> None:
        output_path = REPO_ROOT / "out" / "cli-test-report.json"
        if output_path.exists():
            output_path.unlink()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mergecsv.cli",
                "--dir",
                "demo/sources",
                "--aliases",
                "demo/aliases.json",
                "--out",
                str(output_path.relative_to(REPO_ROOT)),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(result.stdout.count("\n"), 1)
        self.assertIn("合并行数: 6", result.stdout)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(report["summary"]["sources"], 3)
