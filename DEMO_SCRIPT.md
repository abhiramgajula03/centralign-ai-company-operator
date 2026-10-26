# CentrAlign AI demo script

Target length: about 2–3 minutes. Use the local simulation; it never sends real email.

## Before recording

1. Open PowerShell in the project folder and run `python app.py`.
2. Open `http://127.0.0.1:8000` in a browser. Confirm the invoice ledger shows seven sample records.
3. In the dashboard, click **Arm one-time retry demo**. The page should confirm that the next draft write will fail once and be retried.
4. Keep the sample request ready: `Review overdue invoices, prioritize the ones requiring follow-up, draft reminder emails, and prepare a summary for approval.`

## Recording sequence

1. **Set the context (15 seconds):** “This is a local invoice workflow prototype. It reads fictional SQLite records, and approved messages go only to a simulated outbox.”
2. **Give the outcome (10 seconds):** Paste the sample request into the task box and click **Run task**.
3. **Show the plan and tool work (30 seconds):** Point out the generated workflow plan, the `invoice.list` tool event, filtering of the paid and not-yet-due records, the overdue days and balances, then the persisted `reminder.save_draft` events.
4. **Show recovery (15 seconds):** Find the one retry event in the execution timeline. Explain that the one-shot injected write failure was observed, recorded, and retried within the fixed two-attempt bound.
5. **Show human control (30 seconds):** Reject one pending reminder and approve another. Point out that rejection records no outbox entry, while approval creates a simulated outbox row. State clearly that neither action contacts an email service.
6. **Show verification (20 seconds):** Point to the counts for drafts, pending, approved, rejected, and outbox. Show that the app re-read SQLite and matched the expected eligible invoice set and approved drafts to outbox entries.
7. **Show persistence (10 seconds):** Refresh the page and open the task from Recent tasks to show the saved run and decision state remain available.
8. **Close with limits (15 seconds):** “This is deterministic and deliberately narrow: one invoice workflow, fixed policy thresholds, and no model or external connector. I would next add an evaluation harness, company policy configuration, identity and authorization, and a constrained optional model planner.”

## If the retry is not visible

The retry is armed for the next task only. Click the arm button, then immediately run the task. The API alternative is:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/failure-injection
```

Do not claim a retry occurred unless the timeline contains a `retry` event. To show a fresh sample dataset, stop the server and remove `centrAlign.sqlite3` only if you do not need prior demo state; restarting then seeds a new database.

