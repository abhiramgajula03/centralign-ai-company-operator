# CentrAlign AI submission notes

Draft answers for the application form. Replace the link placeholders after publishing and personally verify the declaration before accepting it.

## 1. GitHub repository link

`[ADD PUBLIC GITHUB REPOSITORY LINK AFTER PUBLISHING]`

## 2. Live demo link

`[NOT DEPLOYED — local demo only]`

## 3. Demo video link

`[ADD VIDEO LINK AFTER RECORDING AND UPLOADING]`

## 4. What did you build? (3–5 sentences)

I built a local autonomous invoice follow-up prototype that reads seven fictional invoice records from SQLite, filters and prioritizes overdue unpaid invoices, and saves personalized reminder drafts. It uses a bounded tool registry and records each planning, tool, retry, and approval event in an audit timeline. Each draft requires a human approval or rejection, and approved reminders enter only a simulated local outbox. The task view re-reads persisted records to verify the eligible invoice set, draft decisions, and outbox state.

## 5. Briefly explain your architecture

The browser-native dashboard calls a small Python JSON API served by the same process. A bounded deterministic orchestrator follows a structured invoice workflow and calls two allowlisted tools: `invoice.list` and `reminder.save_draft`. SQLite persists invoices, task state, drafts, decisions, outbox entries, and timestamped events. Approval is enforced in the backend before the simulated outbox write; task results are reconstructed from the database for verification.

## 6. What parts are genuinely autonomous?

For the supported invoice task, the system interprets a limited set of invoice-related requests, generates the workflow plan, reads current records, calculates overdue days and balances, excludes paid and not-yet-due records, applies transparent ranking rules, writes reminder drafts, observes and retries one transient draft-save failure, and verifies persisted outcomes. It pauses for human review before each simulated send. This is bounded deterministic automation, not open-ended or LLM-based reasoning.

## 7. What is hard coded or manually configured?

The workflow plan, accepted intent keywords, priority thresholds, retry limit, fictional seed data, reminder template, SQLite path, and supported tool set are configured in code. The prototype has no LLM, external integrations, company-specific memory, authentication, or configurable policy engine. All send actions are simulated and require individual approval.

## 8. Models, frameworks, APIs, libraries, AI coding tools, or existing projects used

No model or external API was used. The backend uses Python standard-library modules (`http.server`, `sqlite3`, `json`, `datetime`, `uuid`, and `unittest`); the UI uses browser-native HTML, CSS, and JavaScript. OpenAI Codex was used as an AI coding tool to inspect the supplied materials and implement the project. No existing application project or agent framework was used; review the source to understand the implementation before the technical discussion.

## 9. Biggest technical limitation

The agent supports only one predetermined workflow, with a narrow deterministic intent check and hand-authored plan. It does not reason over varied company procedures, use a model, or connect to real business systems; its reliability claims apply only to this local simulated workflow.

## 10. What would you build or change next in two weeks?

I would add an evaluation harness for changing invoice states, database and tool failures, duplicate requests, and approval edge cases; move workflow rules into versioned company policy configuration; add authenticated user identities and audit attribution; and run tasks through a durable worker with safe locking. I would also prototype an optional model planner and draft writer constrained by validated schemas and the existing allowlisted tools, then compare it against the deterministic baseline on a repeatable task set.

## 11. Final declaration — personally verify before accepting

**Draft only:** “I have reviewed and understand the submitted project and can explain its design and limitations. I have disclosed the AI coding tool and any pre-built components used to the best of my knowledge. I have not included confidential company data or used unauthorized access to third-party systems. I am prepared to discuss and modify the implementation in a technical interview.”

Accept this declaration only after you personally confirm each statement is accurate and that you understand the submitted code. Edit it if any part does not describe your own review or use.

