import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import app


class AgentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.old_path = app.DB_PATH
        app.DB_PATH = Path(self.tmp.name) / "test.sqlite3"
        app.FAIL_NEXT_SAVE = False
        app.init_db()

    def tearDown(self):
        app.DB_PATH = self.old_path
        app.FAIL_NEXT_SAVE = False
        self.tmp.cleanup()

    def run_sample(self):
        return app.run_task("Review overdue invoices, prioritize follow-up, draft reminders, and prepare a summary for approval.")

    def test_filter_amount_days_and_priority(self):
        task = self.run_sample()
        invoice_ids = [d["invoice_id"] for d in task["drafts"]]
        self.assertEqual(len(invoice_ids), 5)
        self.assertNotIn("INV-1045", invoice_ids)  # not yet due
        self.assertNotIn("INV-1046", invoice_ids)  # paid
        by_id = {i["id"]: i for i in app.invoice_analysis()}
        self.assertEqual(by_id["INV-1042"]["overdue_days"], 19)
        self.assertEqual(by_id["INV-1042"]["outstanding"], 1840.0)
        self.assertEqual(by_id["INV-1046"]["outstanding"], 0.0)
        self.assertEqual(task["drafts"][0]["invoice_id"], "INV-1044")

    def test_approval_queues_once_and_verifies_persistence(self):
        task = self.run_sample()
        draft = task["drafts"][0]
        changed = app.decide(draft["id"], "approve")
        self.assertEqual(changed["verification"]["outbox_count"], 1)
        self.assertEqual(changed["verification"]["approved"], 1)
        with self.assertRaises(ValueError):
            app.decide(draft["id"], "approve")
        self.assertEqual(app.get_task(task["id"])["verification"]["outbox_count"], 1)

    def test_rejection_never_executes_protected_operation(self):
        task = self.run_sample()
        changed = app.decide(task["drafts"][0]["id"], "reject")
        self.assertEqual(changed["verification"]["outbox_count"], 0)
        self.assertEqual(changed["verification"]["rejected"], 1)
        self.assertTrue(any(e["kind"] == "rejected" for e in changed["events"]))

    def test_one_transient_failure_is_observed_retried_and_saved_once(self):
        app.FAIL_NEXT_SAVE = True
        task = self.run_sample()
        retries = [e for e in task["events"] if e["kind"] == "retry"]
        self.assertEqual(len(retries), 1)
        self.assertEqual(task["verification"]["draft_count"], 5)
        self.assertEqual(len({d["invoice_id"] for d in task["drafts"]}), 5)
        failed_attempt = next(e for e in task["events"] if e["kind"] == "tool" and e["data"].get("attempt") == 2)
        self.assertEqual(failed_attempt["data"]["attempt"], 2)

    def test_retry_limit_and_draft_save_idempotency(self):
        task = self.run_sample()
        invoice = next(i for i in app.invoice_analysis() if i["id"] == task["drafts"][0]["invoice_id"])
        first = app.tool_save_draft(task["id"], invoice)
        second = app.tool_save_draft(task["id"], invoice)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(app.get_task(task["id"])["verification"]["draft_count"], 5)
        # The normal run requires no retry; the retry limit is tested separately below.
        self.assertFalse(any(e["kind"] == "retry" for e in task["events"]))

    def test_retry_bound_stops_after_two_failed_attempts(self):
        original = app.TOOLS["reminder.save_draft"]
        app.TOOLS["reminder.save_draft"] = lambda *args: (_ for _ in ()).throw(RuntimeError("persistent failure"))
        try:
            task = self.run_sample()
        finally:
            app.TOOLS["reminder.save_draft"] = original
        retries = [e for e in task["events"] if e["kind"] == "retry"]
        exhausted = [e for e in task["events"] if e["kind"] == "failed"]
        self.assertEqual(len(retries), 10)
        self.assertEqual(len(exhausted), 5)
        self.assertTrue(all(e["data"]["attempt"] == 2 for e in exhausted))

    def test_restart_style_reopen_uses_persisted_rows(self):
        task = self.run_sample()
        draft_id = task["drafts"][0]["id"]
        app.decide(draft_id, "approve")
        with app.connect():
            pass
        reopened = app.get_task(task["id"])
        self.assertEqual(reopened["verification"]["outbox_count"], 1)
        self.assertEqual(reopened["drafts"][0]["status"], "approved")

    def test_state_survives_a_fresh_python_process(self):
        task = self.run_sample()
        app.decide(task["drafts"][0]["id"], "approve")
        env = os.environ.copy()
        env["CENTRALIGN_DB"] = str(app.DB_PATH)
        script = "import app,sys,json; print(json.dumps(app.get_task(sys.argv[1])['verification']))"
        result = subprocess.run([sys.executable, "-c", script, task["id"]], cwd=Path(__file__).parent,
                                env=env, check=True, capture_output=True, text=True)
        self.assertEqual(__import__("json").loads(result.stdout)["outbox_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
