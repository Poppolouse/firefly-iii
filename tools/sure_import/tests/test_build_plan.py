import importlib.util
import json
import pathlib
import tempfile
import unittest
import zipfile


MODULE = pathlib.Path(__file__).parents[1] / "build_plan.py"
SPEC = importlib.util.spec_from_file_location("build_plan", MODULE)
build_plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_plan)

APPLY_MODULE = pathlib.Path(__file__).parents[1] / "apply_plan.py"
APPLY_SPEC = importlib.util.spec_from_file_location("apply_plan", APPLY_MODULE)
apply_plan = importlib.util.module_from_spec(APPLY_SPEC)
APPLY_SPEC.loader.exec_module(apply_plan)


class BuildPlanTest(unittest.TestCase):
    def test_apply_loader_rejects_unreviewed_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path = pathlib.Path(temp_dir) / "plan.json"
            plan_path.write_text(json.dumps({"format": "sure-to-firefly-api-plan/v1", "operations": [], "manual_review": [{"reason": "review"}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manual_review"):
                apply_plan.load_plan(plan_path)

    def test_reads_ndjson_from_sure_zip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = pathlib.Path(temp_dir) / "sure-export.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("all.ndjson", json.dumps({"type": "Tag", "data": {"id": "t", "name": "checked"}}) + "\n")
            self.assertEqual([{"type": "Tag", "data": {"id": "t", "name": "checked"}}], build_plan.read_export(archive_path))

    def test_builds_operations_and_flags_investment_data(self):
        records = [
            {"type": "Account", "data": {"id": "a1", "name": "Checking", "accountable_type": "Depository", "currency": "EUR"}},
            {"type": "Category", "data": {"id": "c1", "name": "Food"}},
            {"type": "Tag", "data": {"id": "tag1", "name": "receipt"}},
            {"type": "Merchant", "data": {"id": "m1", "name": "Market"}},
            {"type": "Transaction", "data": {"id": "t1", "account_id": "a1", "amount": "-12.50", "currency": "EUR", "date": "2026-01-01", "name": "Groceries", "category_id": "c1", "merchant_id": "m1", "tag_ids": ["tag1"]}},
            {"type": "Trade", "data": {"id": "trade1"}},
        ]
        plan = build_plan.build_plan(records)
        self.assertEqual(4, plan["summary"]["operation_count"])
        transaction = plan["operations"][-1]["payload"]["transactions"][0]
        self.assertEqual("withdrawal", transaction["type"])
        self.assertEqual("Checking", transaction["source_name"])
        self.assertEqual("Market", transaction["destination_name"])
        self.assertTrue(any(item["source_id"] == "trade1" for item in plan["manual_review"]))


if __name__ == "__main__":
    unittest.main()
