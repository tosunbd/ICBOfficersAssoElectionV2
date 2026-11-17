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
| `SA` | `sadmin` | Super Admin | Everything: reports, results, settings, delete a ballot, set any password, watch the entry |
| `Admin` | `admin` | Admin | Reports, results, election set-up, watch the entry (view only) |
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
* A saved ballot can be corrected by the commissioner who owns its number
  ("Your saved ballots"). Corrections are marked in the register, the reports
  ("Manual") and the audit log.
* The three desks work at the same time. SA and Admin see each desk live under
  **Ballot Entry · Live**, including the boxes being ticked before saving, and
  can open any saved ballot — view only.

## Pages

| Page | URL | Who |
|---|---|---|
| Sign in | `/election/admin/login` | all |
| Ballot entry / live monitor | `/election/admin/entry` | EC: entry · SA, Admin: monitor |
| Overview, Results, **Reports**, Ballots, Elections, Candidates, Audit log, Settings | `/election/admin/...` | SA, Admin |
| Dashboard (projector) | `/election/dashboard` | everyone; refreshed every 2 seconds |

The Reports page (Result Summary and Ballot-wise Vote Tally, print / PDF / CSV)
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
.venv\Scripts\python -m pytest        # 31 tests: users, ranges, numbering, null-vote rules, reports
cd ..\icbOfficerAssoUI
npm run lint && npm run build
```

## Layout

```
icbOfficerAssoAPI/app/routers/entry.py          ballot entry API (ranges, numbering, live drafts)
icbOfficerAssoAPI/app/services/ballot_service.py  the counting rules
icbOfficerAssoAPI/app/seed.py                   users + the 2026 ballot
icbOfficerAssoUI/src/app/admin/entry/page.tsx   entry desk and live monitor
icbOfficerAssoUI/src/components/entry/BallotPaper.tsx   the ballot paper form
```
