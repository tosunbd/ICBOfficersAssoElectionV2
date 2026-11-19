# ICB Officers' Association Election System — V2 (ballot entry)

The three Election Commissioners enter the paper ballots on a form that looks
exactly like the printed ballot. Every saved ballot goes straight into the
SQLite database, and the results, the dashboard and the reports follow at once.

| Part | Technology |
|---|---|
| Backend API | Python · FastAPI · SQLAlchemy (async) · SQLite |
| Frontend | Next.js 16 · React 19 · TypeScript |
| Live updates | Dashboard re-reads the summary every 2 seconds (plus an instant push on every save) |

## Users

| Username | Password | Role | Does |
|---|---|---|---|
| `SA` | `sadmin` | Super Admin | Everything: reports, results, settings, **approve corrections**, **edit any ballot**, delete a ballot, set any password, watch the entry |
| `Admin` | `admin` | Admin | Reports, results, election set-up, **approve corrections**, **edit any ballot**, watch the entry |
| `EC1` | `EC1` | Election Commissioner 1 | Enters ballots **001 – 150** |
| `EC2` | `EC2` | Election Commissioner 2 | Enters ballots **151 – 300** |
| `EC3` | `EC3` | Election Commissioner 3 | Enters ballots **301 – 455** |

Usernames are not case sensitive; passwords are. Change the passwords under
**Settings** before the real count (the Super Admin can set anyone's).
The number ranges are `ENTRY_RANGES` in `.env`.

## Ballot entry (EC1, EC2, EC3)

* After signing in, a commissioner lands on the entry form with the next ballot
  number already filled in (001, 002, 003 …). Numbers come one by one: a number
  cannot be skipped, entered twice, or taken from another commissioner's range
  (EC1 cannot enter 160, EC2 cannot enter 320).
* Click a box (or the candidate's name) to put the X. **Select all**, at the
  right of each "ভোটার নং ও প্রার্থীর নাম" heading, ticks or clears every box
  of that side.
* **Save & next ballot** (or `Ctrl` + `Enter`) writes the ballot to the
  database, clears the form and shows the next number.
* Several boxes of one post may be ticked, as on the paper. The rules decide:

  | Post | Votes allowed | More than that |
  |---|---|---|
  | Every post (সভাপতি … আপ্যায়ন সম্পাদক) | 1 | all marks of that post are a **null vote** |
  | নির্বাহী সদস্য | 3 | all নির্বাহী সদস্য marks of that ballot are a **null vote** |

  Null marks are shown in red on the form and are never counted; the other
  posts of the same ballot count as usual. The form asks for confirmation
  before saving a ballot with null votes or a blank ballot.
* **Blank ballot:** a voter who votes for nobody. Save the form with no box
  ticked (and confirm): the paper is counted as a ballot, with no vote for any
  candidate.
* The three desks work at the same time. SA and Admin see each desk live under
  **Ballot Entry · Live**, including the boxes being ticked before saving, and
  can open any saved ballot.

## Correcting a wrong entry (needs approval)

A saved ballot is never changed by the desk itself.

1. The commissioner opens the ballot from **Your saved ballots** (own number
   range only), changes the ticks and presses **Send for approval**.
2. The corrected ticks are stored in a separate table (`ballot_corrections`).
   **Nothing is counted from it**: the ballot, the totals, the dashboard and the
   reports stay exactly as they were.
3. SA or Admin sees the request under **Ballot Entry · Live** (and a notice on
   the Overview), can compare *Saved* against *Corrected* on the ballot paper,
   and presses **Approve** or **Reject**.
   * **Approve** — the ballot's votes are replaced in the real tables and the
     totals, the dashboard and the reports change at once. The ballot is marked
     "Corrected" (who asked, who approved); the reports show it as "Manual".
   * **Reject** — nothing changes.
4. Until a decision the commissioner can change the request or **withdraw** it,
   and sees the outcome of each request under "Your corrections".

Every request, approval, rejection and withdrawal is written to the audit log.

## Editing a ballot on the admin side

SA and Admin can change any saved ballot of any range (001 to 455) themselves:
**Ballots** → **Edit**, or open the ballot under **Ballot Entry · Live** and
press **Edit**. Change the ticks and press **Save changes**. No approval step:
the totals, the dashboard and the reports change at once, the ballot is marked
"Corrected" with the name of who edited it, and the before/after ticks are
written to the audit log. The Election Commissioners do not have this option;
their corrections still need approval.

## Pages

| Page | URL | Who |
|---|---|---|
| Sign in | `/election/admin/login` | all |
| Ballot entry / live monitor | `/election/admin/entry` | EC: entry · SA, Admin: monitor |
| Overview, Results, **Reports**, Ballots, Elections, Candidates, Audit log, Settings | `/election/admin/...` | SA, Admin |
| Dashboard (projector) | `/election/dashboard` | everyone; refreshed every 2 seconds |

The Reports page (1 Result Summary, 2 Ballot-wise Vote Tally, 3 Panel Votes with Panel Left / Panel Right, 4 Null Votes; print / PDF / CSV)
is the same as in the previous system.

## Running (Windows)

1. **`0. install.bat`** — once per PC (Python, Node.js, packages, UI build, IIS `/election`).
2. **`1. Start.bat`** — every time. **`2. Stop.bat`** stops it.
3. **`3. DBCLEAR.bat`** — before the real count: backs the database up to
   `data\Archive` and empties it (the five logins stay). On the next start the
   2026 election, its 13 posts and 30 candidates are created again.

The previous system (`ICBOfficersAssoElection`) uses the same ports (8000,
3000) and the same IIS address, so stop it before starting this one.

The database is `data\icbOfficerAssoDB<year>.db`; it is created on the first
start together with the users and the election.

## Tests

```
cd icbOfficerAssoAPI
.venv\Scripts\python -m pytest        # 34 tests: users, ranges, numbering, null-vote rules, blank ballots, approvals, reports
cd ..\icbOfficerAssoUI
npm run lint && npm run build
```

## Layout

```
icbOfficerAssoAPI/app/routers/entry.py          ballot entry API (ranges, numbering, live drafts, corrections and approval)
icbOfficerAssoAPI/app/models/ballot_correction.py   corrections waiting for approval (separate table)
icbOfficerAssoAPI/app/services/ballot_service.py  the counting rules
icbOfficerAssoAPI/app/seed.py                   users + the 2026 ballot
icbOfficerAssoUI/src/app/admin/entry/page.tsx   entry desk and live monitor
icbOfficerAssoUI/src/components/entry/BallotPaper.tsx   the ballot paper form
```
