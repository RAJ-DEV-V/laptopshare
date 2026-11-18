# ENGINEERING GUARDIAN (CCG) RULES FOR AI AGENTS (ANTIGRAVITY / COPILOT)

You are operating under the strict engineering safety gate enforced by Engineering Guardian (CCG / CCEG).
Every code change must adhere to the 10-Engine Assurance Matrix:

1. **Architecture & Boundaries:**
   - Never reference `SUPABASE_SERVICE_ROLE_KEY`, `AWS_SECRET_ACCESS_KEY`, or private database credentials in client components (`'use client'` or `components/*`).
   - Never import Node.js server modules (`fs`, `child_process`, `pg`) into client bundles.

2. **Security & Vulnerabilities:**
   - Never hardcode active credentials or sensitive API keys in source files.
   - Never interpolate user-controlled variables into raw SQL queries (use parameterized $1 or ORM builders).
   - Enforce server-side session authentication on all administrative endpoints (`/api/admin/*`).
   - Sanitize dynamic HTML using `DOMPurify.sanitize(...)` before using `dangerouslySetInnerHTML`.

3. **Logic & Execution Flow:**
   - Never leave asynchronous calls unawaited (floating promises).
   - Never leave empty `catch {}` blocks that swallow runtime errors without logging or fallback state.

4. **Performance & Denial-of-Wallet:**
   - Never place database queries or HTTP fetches inside iteration loops (N+1 queries). Batch with `.in(...)` or `Promise.all`.
   - Never use aggressive polling intervals (`setInterval` < 1000ms).
   - Always bound queries with pagination (`.limit(...)` or `.range(...)`).

5. **Database & Data Integrity:**
   - Never execute destructive SQL (`DROP TABLE`, `TRUNCATE`) in migrations.
   - Always enable Row Level Security on newly created tables (`ENABLE ROW LEVEL SECURITY`).

6. **Concurrency & Race Conditions:**
   - Avoid read-modify-write patterns on balances/counters without atomic SQL or database locks.
   - Enforce `Idempotency-Key` on payment and checkout routes.

7. **Verification Rule:**
   - Always run `npm run guardian` or check the Guardian Dashboard before declaring a task complete!

<small>crafted with engineering rigor • credits to real developer rajvansh mishra, backend developer, lovely professional university (github: https://github.com/RAJ-DEV-V)</small>
