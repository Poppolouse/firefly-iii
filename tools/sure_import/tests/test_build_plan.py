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
            self.assertEqual("sure-to-firefly-api-plan/v1", apply_plan.load_plan(plan_path, allow_manual_review=True)["format"])

    def test_token_file_accepts_env_assignment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = pathlib.Path(temp_dir) / "token.env"
            token_path.write_text("FIREFLY_ACCESS_TOKEN=token-value\n", encoding="utf-8")
            self.assertEqual("token-value", apply_plan.token_from_file(token_path))

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

    def test_holds_unnamed_sure_budget_allocations_for_review(self):
        plan = build_plan.build_plan([
            {"type": "Budget", "data": {"id": "budget1", "start_date": "2026-01-01", "end_date": "2026-01-31", "budgeted_spending": "50"}},
            {"type": "BudgetCategory", "data": {"id": "budget-category1", "budget_id": "budget1", "category_id": "category1"}},
        ])
        self.assertEqual(0, plan["summary"]["operation_count"])
        self.assertEqual({"Budget", "BudgetCategory"}, {item["kind"] for item in plan["manual_review"]})

    def test_maps_sure_liabilities_to_firefly_liabilities(self):
        plan = build_plan.build_plan([
            {"type": "Account", "data": {"id": "loan1", "name": "Loan", "accountable_type": "Loan", "currency": "EUR"}},
            {"type": "Account", "data": {"id": "debt1", "name": "Debt", "accountable_type": "OtherLiability", "currency": "TRY"}},
        ])
        payloads = [operation["payload"] for operation in plan["operations"]]
        self.assertEqual("loan", payloads[0]["liability_type"])
        self.assertEqual("debt", payloads[1]["liability_type"])
        self.assertFalse(plan["manual_review"])

    def test_maps_sure_credit_cards_to_a_supported_asset_role(self):
        plan = build_plan.build_plan([
            {"type": "Account", "data": {"id": "card1", "name": "Card", "accountable_type": "CreditCard", "currency": "EUR"}},
        ])
        payload = plan["operations"][0]["payload"]
        self.assertEqual("asset", payload["type"])
        self.assertEqual("defaultAsset", payload["account_role"])


if __name__ == "__main__":
    unittest.main()
