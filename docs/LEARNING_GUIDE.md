# Learning Guide: Placement Application Tracker

This guide is for anyone (including me in an interview) who wants to understand every line of this
project. Read it with the code open beside it.

**Contents**

1. [The big picture](#1-the-big-picture)
2. [One request, start to finish](#2-one-request-start-to-finish)
3. [File-by-file tour (reading order)](#3-file-by-file-tour-reading-order)
4. [How validation works](#4-how-validation-works)
5. [The SQL behind /api/stats](#5-the-sql-behind-apistats)
6. [Interview questions and answers](#6-interview-questions-and-answers)
7. [Practice exercises](#7-practice-exercises)

---

## 1. The big picture

```
Browser (HTML + CSS + vanilla JS)
   │  fetch("/api/...")  →  HTTP request with JSON
   ▼
Uvicorn  (the web server process, speaks HTTP)
   ▼
FastAPI  (routing: which Python function handles this URL + method?)
   │  Pydantic validates the input  →  422 if invalid
   ▼
Router function  (app/routers/*.py)
   ▼
crud.py  (builds queries with the SQLAlchemy ORM)
   ▼
SQLAlchemy  (turns Python into SQL with bound parameters)
   ▼
SQLite  (tracker.db, two tables)
```

The answer travels back up the same path: rows → ORM objects → Pydantic `ApplicationOut` → JSON →
`app.js` → DOM.

Three layers, each with one job:

| Layer | Files | Job |
|---|---|---|
| HTTP / API | `main.py`, `routers/*.py`, `schemas.py` | URLs, status codes, input/output validation |
| Data access | `crud.py` | every query lives here |
| Storage | `models.py`, `database.py` | tables, columns, relationships, connection |

The routers never write SQL, and `crud.py` never deals with HTTP status codes. That separation is what
lets me test, change or swap one layer without touching the others.

---

## 2. One request, start to finish

**Scenario:** in the table, I change Freshworks from **OA** to **Interview** using the status dropdown.

### Step 1: Click (browser event)

Each row's dropdown is a `<select class="status-select">`. There is **no listener on each select**.
Instead, one listener sits on the `<tbody>` (*event delegation*, in `static/app.js`):

```js
tableBody.addEventListener("change", (event) => {
  if (!event.target.matches(".status-select")) return;
  const id = Number(event.target.closest("tr").dataset.id);   // the <tr> carries data-id="7"
  const app = currentApplications.find((a) => a.id === id);
  changeStatus(app, event.target.value, event.target);
});
```

The `change` event *bubbles* up from the `<select>` to the `<tbody>`, so one listener serves every
row, including rows drawn later.

### Step 2: fetch (HTTP request)

`changeStatus()` calls the small `api()` helper, which wraps `fetch`:

```js
await api(`/api/applications/${app.id}/status`, {
  method: "PATCH",
  body: JSON.stringify({ status: newStatus }),
});
```

What actually goes over the network:

```
PATCH /api/applications/7/status HTTP/1.1
Content-Type: application/json

{"status": "Interview"}
```

`await` pauses this function (not the page) until the reply arrives.

### Step 3: Routing (FastAPI)

Uvicorn receives the bytes and hands the request to FastAPI, which matches the method and path
against the decorators in `app/routers/applications.py`:

```python
@router.patch("/applications/{application_id}/status", response_model=ApplicationOut)
def change_status(application_id: int, data: StatusUpdate, db: Session = Depends(get_db)):
    return crud.change_status(db, get_or_404(db, application_id), data.status)
```

FastAPI reads the type hints to decide where each argument comes from:

- `application_id: int` is in the path, so `"7"` is converted to the integer `7` (`"abc"` would give 422).
- `data: StatusUpdate` is a Pydantic model, so it comes from the JSON body.
- `db: Session = Depends(get_db)` is a *dependency*: FastAPI calls `get_db()`, which opens a
  database session and closes it in its `finally` block once the request is done.

### Step 4: Validation (Pydantic)

Before `change_status` runs, Pydantic checks the body against `StatusUpdate`:

```python
class StatusUpdate(BaseModel):
    status: Status        # must be one of the 6 enum values
```

`{"status": "Ghosted"}` would never reach my function. FastAPI answers **422 Unprocessable Entity** with
a list of errors, e.g. `{"detail": [{"loc": ["body", "status"], "msg": "Input should be 'Wishlist', ..."}]}`.

### Step 5: ORM (crud.py)

`get_or_404` calls `crud.get_application` → `db.get(Application, 7)`. If it returns `None`, the router
raises `HTTPException(404)`. Otherwise `crud.change_status` → `record_status_change`:

```python
def record_status_change(application, new_status):
    if application.status == new_status:
        return False                                  # nothing to do, no history row
    application.history.append(StatusHistory(from_status=application.status, to_status=new_status))
    application.status = new_status
    return True
```

I only change **Python objects** here. The session tracks the changes and writes them all on `db.commit()`.

### Step 6: SQL (what SQLAlchemy actually sent)

Captured with `SQL_ECHO=1` while making exactly this request:

```sql
BEGIN (implicit)
SELECT applications.id, applications.company, ... FROM applications WHERE applications.id = ?
  -- params: (7,)
SELECT status_history.id, ... FROM status_history
WHERE ? = status_history.application_id ORDER BY status_history.id
  -- params: (7,)     ← loading application.history (needed for .append)
UPDATE applications SET status=?, updated_at=? WHERE applications.id = ?
  -- params: ('Interview', '2026-10-27 17:57:41.052937', 7)
INSERT INTO status_history (application_id, from_status, to_status, changed_at) VALUES (?, ?, ?, ?)
  -- params: (7, 'OA', 'Interview', '2026-10-27 17:57:41.055718')
COMMIT
```

Notice:

- **One transaction**: the UPDATE and the INSERT commit together. If one failed, neither would be saved,
  so the history can never disagree with the status.
- `updated_at` was set automatically (`onupdate=utc_now` in the model).
- Every value is a `?` **bound parameter**, never pasted into the SQL text (see Q14).

After the commit, `db.refresh(application)` re-reads the row. When the request ends, `get_db` closes the
session; the `ROLLBACK` you may see in the log at that point only ends the read-only transaction that
`refresh` opened.

### Step 7: JSON (response)

The router returns the ORM object. Because of `response_model=ApplicationOut` (with
`from_attributes=True`), FastAPI reads the object's attributes, keeps only the fields declared in the
schema, and serialises them:

```json
{"id": 7, "company": "Freshworks", "status": "Interview", "next_step_date": "2026-10-30",
 "updated_at": "2026-10-27T17:57:41.052937Z", ...}
```

Status code **200 OK**. The `Z` on timestamps means UTC (see `UtcDateTime` in `schemas.py`).

### Step 8: DOM update

Back in the browser, `await api(...)` now resolves. `changeStatus` shows a toast, then calls
`refresh()`, which runs `loadStats()` and `loadApplications()` in parallel (`Promise.all`).
`renderTable` rebuilds the rows with `document.createElement` + `textContent`, and `renderFunnel`
sets each bar's `style.width`. The CSS `transition: width 0.4s` makes the Interview bar grow smoothly.

If anything failed (e.g. 404), `api()` throws, the `catch` puts the dropdown back to its old value and
shows the error message in a red toast.

---

## 3. File-by-file tour (reading order)

Read in this order: each file only uses things from the files before it.

1. **`app/database.py`** – `create_engine` (how to connect), `SessionLocal` (a factory for sessions),
   `Base` (parent class of all models), `get_db` (FastAPI dependency: one session per request). Also a
   small event listener that turns on `PRAGMA foreign_keys=ON`, because SQLite ignores foreign keys by default.
2. **`app/models.py`** – the `Status` enum and the two tables. `Mapped[str | None]` means the column is
   nullable. `relationship(..., cascade="all, delete-orphan")` gives `application.history` and deletes
   history rows along with their application. `ForeignKey(..., ondelete="CASCADE")` is the same rule at
   database level.
3. **`app/schemas.py`** – the API contract. `ApplicationCreate` (input, with the date-order rule),
   `ApplicationUpdate` (all fields optional), `StatusUpdate`, `ApplicationOut` / `StatusHistoryOut`
   (output), `StatsOut`. Models describe tables; schemas describe JSON. Keeping them apart means a new
   database column is never exposed by accident.
4. **`app/crud.py`** – all queries. The top half is CRUD (`create_application`, `list_applications`, ...);
   the bottom half computes stats with SQL aggregation. Start with `record_status_change`; it is the
   heart of the history feature.
5. **`app/routers/applications.py`** – the HTTP layer for applications: one small function per endpoint,
   `get_or_404` for missing ids, the date check for partial updates, and the CSV generator.
6. **`app/routers/stats.py`** – calls the stats functions in `crud.py` and calculates the conversion
   percentages.
7. **`app/main.py`** – creates `app = FastAPI(...)`, creates tables at startup (`lifespan`), includes the
   two routers, adds `/health`, and serves `static/` plus `index.html` at `/`.
8. **`static/index.html`** – the page skeleton: header, 4 stat cards, form, funnel, table, `<dialog>`.
   It has no data in it; `app.js` fills everything in.
9. **`static/app.js`** – read it top to bottom; it is split into numbered sections: constants → helpers
   (`api`, dates, `createElement`) → stats & funnel → table → form → row actions → event wiring.
10. **`static/style.css`** – CSS variables at the top (`--bg`, `--accent`, status colours); dark mode just
    redefines them inside `@media (prefers-color-scheme: dark)`. Layout uses CSS Grid.
11. **`seed.py`** – 15 sample applications with dates relative to today, and back-dated history rows so the
    funnel and timelines look realistic.
12. **`tests/conftest.py`** – the isolated test database and the `client` / `make_application` fixtures.
13. **`tests/test_*.py`** – each test is short: arrange (create data), act (call the API), assert.
14. **`Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`** – packaging and automation (Q9, Q10).

---

## 4. How validation works

Validation happens **twice**, on purpose:

| Where | How | Why |
|---|---|---|
| Browser (`validate()` in `app.js`) | plain `if` checks, messages under each field | instant, friendly feedback |
| Server (`schemas.py`, router) | Pydantic `Field(ge=0, min_length=1, pattern=...)`, `@model_validator`, enum types | the real guard: anyone can call the API with curl and skip the browser |

Server rules and where they live:

- `company`, `role` required and not blank → `Field(min_length=1)` + `str_strip_whitespace=True`
- `status` one of six → type `Status` (an enum)
- `ctc_lpa ≥ 0` → `Field(ge=0)`
- `job_link` starts with http(s) → `Field(pattern=r"^https?://\S+$")`
- `next_step_date ≥ applied_on` → `@model_validator` on create. On update the body may contain only
  one of the two dates, so the router checks the **merged** values (new value, or the stored one) and
  raises `HTTPException(422, "next_step_date cannot be before applied_on")`.
- Explicit `null` for `company`/`role`/`status` on update → `@field_validator("company", "role", "status")`.

---

## 5. The SQL behind /api/stats

Printed by running the server with `SQL_ECHO=1` and calling `GET /api/stats` (seeded sample data).
`/api/stats` sends **four** queries.

### 5.1 Counts per status

```python
select(Application.status, func.count(Application.id)).group_by(Application.status)
```

```sql
SELECT applications.status, count(applications.id) AS count_1
FROM applications GROUP BY applications.status
```

`total` is the sum of these counts and `active` is Applied + OA + Interview. Statuses with no rows are
filled with 0 in Python, because `GROUP BY` returns no row for them.

### 5.2 Funnel: how many applications ever reached each stage

Exactly as SQLAlchemy generated it:

```sql
SELECT coalesce(sum(CASE WHEN (anon_1.best_stage >= ?) THEN ? ELSE ? END), ?) AS "Applied",
       coalesce(sum(CASE WHEN (anon_1.best_stage >= ?) THEN ? ELSE ? END), ?) AS "OA",
       coalesce(sum(CASE WHEN (anon_1.best_stage >= ?) THEN ? ELSE ? END), ?) AS "Interview",
       coalesce(sum(CASE WHEN (anon_1.best_stage >= ?) THEN ? ELSE ? END), ?) AS "Offer"
FROM (SELECT status_history.application_id AS application_id,
             max(CASE status_history.to_status WHEN ? THEN ? WHEN ? THEN ? WHEN ? THEN ? WHEN ? THEN ? ELSE ? END) AS best_stage
      FROM status_history GROUP BY status_history.application_id) AS anon_1
-- params: (1, 1, 0, 0,  2, 1, 0, 0,  3, 1, 0, 0,  4, 1, 0, 0,
--          'Applied', 1, 'OA', 2, 'Interview', 3, 'Offer', 4, 0)
```

The same query with the parameters filled in, so it is easier to read:

```sql
-- Inner query: the best (highest) stage each application ever had
SELECT application_id,
       MAX(CASE to_status
             WHEN 'Applied'   THEN 1
             WHEN 'OA'        THEN 2
             WHEN 'Interview' THEN 3
             WHEN 'Offer'     THEN 4
             ELSE 0                      -- Wishlist and Rejected are not stages
           END) AS best_stage
FROM status_history
GROUP BY application_id;

-- Outer query: count applications whose best stage is at least 1, 2, 3, 4
SELECT COALESCE(SUM(CASE WHEN best_stage >= 1 THEN 1 ELSE 0 END), 0) AS "Applied",
       COALESCE(SUM(CASE WHEN best_stage >= 2 THEN 1 ELSE 0 END), 0) AS "OA",
       COALESCE(SUM(CASE WHEN best_stage >= 3 THEN 1 ELSE 0 END), 0) AS "Interview",
       COALESCE(SUM(CASE WHEN best_stage >= 4 THEN 1 ELSE 0 END), 0) AS "Offer"
FROM (<inner query>) AS anon_1;
```

How to explain it:

- `CASE ... END` maps each status name to a number so stages can be compared.
- `MAX(...) ... GROUP BY application_id` keeps one row per application: its furthest stage. So
  `Applied → OA → Rejected` has `best_stage = 2`.
- `SUM(CASE WHEN best_stage >= 2 THEN 1 ELSE 0 END)` is a *conditional count*: it adds 1 for every
  application that got at least as far as OA.
- `COALESCE(..., 0)` turns `NULL` (what `SUM` returns on an empty table) into 0.
- Why `>=`? Reaching Interview implies you got past OA, even if a company skipped the OA.

With the sample data the result is `Applied 13, OA 9, Interview 6, Offer 2`. The router then computes
`9/13 = 69.2 %`, `6/9 = 66.7 %`, `2/6 = 33.3 %`.

### 5.3 Upcoming next steps (7 days)

```sql
SELECT count(applications.id) AS count_1
FROM applications
WHERE applications.next_step_date BETWEEN ? AND ? AND applications.status != ?
-- params: ('2026-10-27', '2026-11-03', 'Rejected')
```

`BETWEEN` includes both ends, so "today" and "today + 7" both count.

### 5.4 Average offer CTC

```sql
SELECT avg(applications.ctc_lpa) AS avg_1
FROM applications
WHERE applications.status = ?
-- params: ('Offer',)
```

`AVG` ignores `NULL`s (offers without a CTC) and returns `NULL` when there are no offers; the API sends
that as `null`.

**Why SQL rather than a Python loop?** The database does the counting next to the data and returns four
small rows, instead of sending every row to Python. With 100,000 applications that difference matters,
and with an index on `status`/`next_step_date` the database can do it efficiently.

---

## 6. Interview questions and answers

**Q1. What is REST, and is your API RESTful?**
REST is a style for web APIs: everything is a *resource* with a URL (`/api/applications/7`), and you act
on it with standard HTTP methods; each request is *stateless* (it carries everything the server needs).
My API follows that: nouns in URLs, methods for actions, JSON representations, meaningful status codes.
The one action-like URL is `PATCH /applications/{id}/status`, a sub-resource I chose because a status
change has a side effect (a history row).

**Q2. Which HTTP methods and status codes do you use?**
`GET` read, `POST` create, `PUT` update, `PATCH` change status, `DELETE` remove.
`200 OK` normal success; `201 Created` after POST; `204 No Content` after DELETE (no body);
`404 Not Found` unknown id; `422 Unprocessable Entity` the JSON is well-formed but breaks a rule
(negative CTC, unknown status, dates in the wrong order). A server bug would be `500`.
*PUT vs PATCH:* PUT normally replaces the whole resource and PATCH changes part of it. I kept a single
`PUT` that accepts partial bodies (only the fields sent are changed) to keep the API small, and I documented
that choice. Both are idempotent here: sending the same request twice gives the same result.

**Q3. What is an ORM, and why use SQLAlchemy?**
An Object-Relational Mapper maps tables to classes and rows to objects: `Application` is the
`applications` table, and `application.status = "OA"` becomes an `UPDATE`. Benefits: less hand-written
SQL, queries built from Python expressions (safe parameters, works on SQLite and PostgreSQL), and
relationships like `application.history`. I still know the SQL it generates (section 5), which matters
when debugging performance.

**Q4. Why Pydantic?**
It turns type hints into runtime validation and conversion: `"2026-10-30"` becomes a `date`, `-1` for
`ctc_lpa` is rejected by `Field(ge=0)`, and `"Ghosted"` is rejected by the `Status` enum. FastAPI uses
it automatically, so invalid input gets a 422 with the exact field and reason before my code runs.
Output schemas (`ApplicationOut`) control exactly which fields are returned.

**Q5. Explain the one-to-many relationship.**
One application has many `status_history` rows. The `status_history.application_id` column is a
**foreign key** to `applications.id`. In SQLAlchemy, `Application.history` and
`StatusHistory.application` are the two sides (`back_populates`). `ondelete="CASCADE"` plus the ORM
`cascade="all, delete-orphan"` mean deleting an application deletes its history too; a test checks this.
As SQL: `SELECT ... FROM applications JOIN status_history ON status_history.application_id = applications.id`.

**Q6. How do filtering, search and sorting work?**
`list_applications` starts with `select(Application)` and adds clauses only for the parameters given:
`status` adds `WHERE status = ?`; `q` adds `WHERE lower(company) LIKE '%' || lower(?) || '%' OR lower(role) LIKE ...`
(that is what `icontains` generates; `autoescape=True` makes `%` and `_` in the search text literal);
`sort` picks an `ORDER BY` from a dict. Invalid `status` or `sort` values are rejected with 422, because
their types are an enum and a `Literal`. On the frontend, the search box is *debounced* (it waits 250 ms after
the last keystroke) so we don't send a request per key.

**Q7. How does the CSV export stream?**
`csv_lines()` is a **generator**: it `yield`s the header, then one CSV line per application. I pass it to
`StreamingResponse`, which sends each piece as it is produced (`Transfer-Encoding: chunked`) instead of
building the whole file in memory first. Python's `csv` module handles commas and quotes inside values.
The `Content-Disposition: attachment; filename="applications.csv"` header makes the browser download it.
For a very large table I'd also fetch rows in batches (`yield_per`) rather than loading them all.

**Q8. How do the tests isolate the database?**
`tests/conftest.py` creates a separate engine on `sqlite://` (in-memory). Before each test the tables are
created, after it they are dropped, so every test starts empty and tests can't affect each other.
`app.dependency_overrides[get_db]` makes every route use the test session instead of the real one.
`StaticPool` keeps a single connection, because each new connection to an in-memory SQLite database would
otherwise see its own empty database. `TestClient` calls the app in-process, with no real server or network.

**Q9. What does Docker do here?**
The `Dockerfile` describes an image: start from `python:3.12-slim`, install the pinned requirements, copy
the code, run as a non-root user, and start Uvicorn on port 8000. `docker-compose.yml` runs it with one
command, maps port 8000, sets `DATABASE_URL` to `/data/tracker.db` and mounts a named volume there so the
data survives container restarts. It also has a health check that calls `/health`. The point is that it runs
the same way on any machine.

**Q10. What does CI do?**
`.github/workflows/ci.yml` runs on every push and pull request: GitHub starts a fresh Ubuntu machine, checks
out the code, installs Python 3.12 and the requirements, and runs `pytest`. A second job checks that the
Docker image still builds. If anything fails, the commit is marked red, so a broken change is caught
before it is merged.

**Q11. How would you add login (JWT)?**
Add a `users` table (email, hashed password using bcrypt or argon2, never plain text) and a `user_id`
foreign key on `applications`. `POST /auth/login` checks the password and returns a signed JWT (with the
user id and an expiry). The browser sends it as `Authorization: Bearer <token>`. A FastAPI dependency
`get_current_user` verifies the signature and expiry and loads the user; every query in `crud.py` then
filters by `user_id`, so users only see their own applications. Secrets go in environment variables.

**Q12. How would you scale this to many users or move to PostgreSQL?**
SQLite allows only one writer at a time, which suits a single user. For many users: PostgreSQL, by
changing `DATABASE_URL` (the ORM code stays the same) and using Alembic for schema migrations instead of
`create_all`. Then run several Uvicorn workers or containers behind a load balancer (the app is
stateless, so this works), add indexes for the common filters (already on `status`, `company`,
`next_step_date`), paginate the list endpoint, and cache `/api/stats` if it gets expensive.

**Q13. What is CORS? Did you need it?**
Browsers block JavaScript on one *origin* (scheme + host + port) from reading responses from another
origin unless that server allows it with `Access-Control-Allow-Origin` headers. That is Cross-Origin
Resource Sharing. I didn't need it: FastAPI serves both the page and the API from the same origin. If the
frontend were hosted separately (e.g. on Netlify), I'd add FastAPI's `CORSMiddleware` with an explicit
list of allowed origins, not `*`.

**Q14. How is SQL injection prevented?**
User input never becomes part of the SQL text. SQLAlchemy sends values as **bound parameters** (the `?`s in
section 5); the database treats them as data, so a search for `'; DROP TABLE applications; --` is just a
string that matches nothing. I never build SQL with f-strings. On the frontend the related risk is XSS, so
all server data is written with `textContent`, never `innerHTML`.

**Q15. Why vanilla JavaScript instead of React?**
The UI is one page: a form, a table, a funnel and a dialog. Plain JS covers that with no build step and
no dependencies, and it shows I understand the basics that frameworks wrap: `fetch` and promises,
`async/await`, DOM creation, event delegation and re-rendering after a change. If the UI grew (many pages,
shared state, reusable components), I'd move to React or Vue.

**Bonus: why store history in a separate table and not just the current status?**
The current status alone can't answer "how many applications got to the interview stage?" A rejected
application would look the same whether it failed the OA or the final interview. The history table keeps
every transition, which powers the timeline and the funnel.

**Bonus: what if two table requests come back in the wrong order?**
If I change the status filter and then the sort, two requests are in flight. The network doesn't
guarantee order, so the *older* reply could arrive last and overwrite the newer table. `loadApplications`
numbers each request (`latestTableRequest`) and ignores any reply that isn't from the latest one. I found
this race condition while testing the UI with headless Chrome.

**Bonus: why are timestamps stored in UTC?**
The server and the user may be in different time zones (a Docker container runs in UTC). Storing UTC and
letting the browser convert (`toLocaleString`) avoids ambiguity. SQLite drops time zone info, so
`UtcDateTime` in `schemas.py` re-attaches UTC before the JSON is sent.

---

## 7. Practice exercises

Doing these yourself is the fastest way to own the code:

1. Add a `source` field (Campus / Referral / LinkedIn): model column, schemas, form field, table cell, a test.
   Delete `tracker.db` afterwards (no migrations yet) and re-run `python seed.py`.
2. Add `GET /api/stats` field `rejected_after_interview` (applications whose history contains Interview
   and whose current status is Rejected). Write the test first.
3. Add pagination: `limit` and `offset` query parameters on `GET /api/applications`.
4. Run the server with `SQL_ECHO=1`, use the app, and match each SQL statement to the line of Python that
   caused it.
5. Break something on purpose (e.g. remove `ge=0` from `ctc_lpa`) and watch which test fails.
