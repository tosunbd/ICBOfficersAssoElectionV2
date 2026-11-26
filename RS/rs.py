r"""RS - read a whole folder of scanned ballots and write the two result reports.

    rs.bat                      (double click)   or   python rs.py ["folder of the scans"]

Asks for the folder that holds the scanned ballots (images and / or PDFs), reads
every file with the reader of the counting system (folder rs_engine) and writes,
next to this program:

    1. Result Summary.pdf            elected candidates + votes of every candidate
    2. Ballot-wise Vote Tally.pdf    one line per ballot (1 / 0) + ballots to check by hand

No database, no server, no screen: nothing is moved, renamed or changed in the
folder of the scans.  The candidates come from candidates.csv beside this file
(ballot order: first candidate of a row = left side of the paper).
"""

from __future__ import annotations

import base64
import csv
import html
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ----------------------------------------------------------------- settings
COUNCIL_NO = 20                 # ২০তম কার্যনির্বাহী পরিষদ
ELECTION_YEAR = 2026
REGISTERED_VOTERS = 0           # number of voters; 0 = not printed (no turnout figure)
SEATS_BY_POST = {13: 3}         # post no -> seats; every other post has 1 seat
SIGNATORIES = ["Member, Election Commission", "Member, Election Commission", "Chief Election Commissioner"]
CANDIDATES_CSV = HERE / "candidates.csv"
OUTPUT_DIR = HERE               # the reports are written beside this program
SUMMARY_NAME = "1. Result Summary"
TALLY_NAME = "2. Ballot-wise Vote Tally"
# ---------------------------------------------------------------------------

try:
    from rs_engine.ocr_service import SUPPORTED_SUFFIXES, apply_post_rules, ocr_service
    from rs_engine.paper_number import file_paper_no, read_paper_no, same_paper
    from rs_engine.settings import settings
except ImportError as exc:  # a package is missing: rs.bat installs them
    print(f"A Python package is missing: {exc}")
    print("Run rs.bat, or:  python -m pip install opencv-python-headless numpy Pillow pypdfium2")
    sys.exit(2)

BN_DIGITS = "০১২৩৪৫৬৭৮৯"
e = html.escape


# ------------------------------------------------------------------- data
@dataclass
class Candidate:
    id: int
    voter_no: str
    name_en: str
    name_bn: str
    order: int            # place within the post on the ballot (0 = first / left)
    post_no: int


@dataclass
class Post:
    no: int
    name_en: str
    name_bn: str
    seats: int
    candidates: list[Candidate] = field(default_factory=list)


@dataclass
class Sheet:
    """One ballot paper = one page of one scanned file."""
    file: str
    page: int
    pages: int
    paper_no: str | None            # number read from the box on the paper
    counted: list[int]              # candidate ids that got a vote
    void_marks: int                 # touched boxes that are not counted (over-vote)
    reasons: list[str]              # why somebody should look at this paper

    @property
    def label(self) -> str:
        return self.file if self.pages == 1 else f"{self.file}  p.{self.page}"

    @property
    def number(self) -> str:
        return self.paper_no.zfill(settings.BALLOT_NUMBER_DIGITS) if self.paper_no else "?"


def load_candidates(path: Path) -> tuple[list[Post], list[dict], dict[int, int]]:
    """Posts with their candidates, the box layout for the reader, seats per post."""
    if not path.exists():
        raise SystemExit(f"candidates.csv not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        # ballot order = the CSV order within each post (sorted() is stable)
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["post_no"]))
    posts: dict[int, Post] = {}
    layout: list[dict] = []
    row_index, slot = -1, 0
    columns = max(1, settings.BALLOT_COLUMNS)
    for number, r in enumerate(rows, start=1):
        no = int(r["post_no"])
        if no not in posts:
            posts[no] = Post(no, r["post_en"].strip(), (r.get("post_bn") or "").strip(), SEATS_BY_POST.get(no, 1))
            row_index, slot = row_index + 1, 0
        elif slot == columns:
            row_index, slot = row_index + 1, 0
        post = posts[no]
        post.candidates.append(Candidate(
            number, r["voter_no"].strip(), r["name_en"].strip(), (r.get("name_bn") or "").strip(), len(post.candidates), no,
        ))
        layout.append({"candidate_id": number, "position_id": no, "row_index": row_index, "col_index": slot})
        slot += 1
    if not layout:
        raise SystemExit(f"No candidates in {path}")
    return list(posts.values()), layout, {p.no: p.seats for p in posts.values()}


# ---------------------------------------------------------------- reading
def natural(name: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name.lower())]


def is_own_output(path: Path) -> bool:
    return path.suffix.lower() == ".pdf" and path.stem.startswith((SUMMARY_NAME, TALLY_NAME))


def scan_files(folder: Path) -> list[Path]:
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES and not is_own_output(p)]
    return sorted(files, key=lambda p: natural(p.name))


def read_file(path: Path, layout: list[dict], seats: dict[int, int], names: dict[int, str], posts: dict[int, Post]) -> list[Sheet]:
    """Every page of one file, read and judged exactly as the counting system does
    (BallotProcessor._store_page): a touched box is a vote unless its post has more
    touched boxes than seats."""
    pages = ocr_service.process_file(path, layout)
    if not pages:
        raise ValueError("the file has no page")
    sheets = []
    for page_no, page in enumerate(pages, start=1):
        if page.boxes_detected == 0:
            raise ValueError("no ballot found on the page (no boxes)" + (f", page {page_no}" if len(pages) > 1 else ""))
        over_voted = apply_post_rules(page.marks, seats)
        touched = [m for m in page.marks if m.is_marked]
        counted = [m.candidate_id for m in touched if not m.void_reason]
        reasons: list[str] = []
        if not page.layout_ok:
            reasons.append(f"Boxes not all found ({page.boxes_detected} of {page.boxes_expected}): check every post")
        for post_no in sorted(over_voted):
            marks = sum(1 for m in touched if m.position_id == post_no)
            reasons.append(f"{posts[post_no].name_en}: {marks} boxes marked, {seats[post_no]} allowed - not counted")
        unclear = [m for m in touched if m.unclear and not m.void_reason]
        for m in unclear:
            reasons.append(f"Unclear mark counted for {names[m.candidate_id]} ({m.unclear})")
        low = any(m.confidence < settings.LOW_CONFIDENCE_THRESHOLD for m in page.marks if m.box is not None)
        if low and page.layout_ok and not unclear:
            light = [names[m.candidate_id] for m in page.marks
                     if m.box is not None and m.confidence < settings.LOW_CONFIDENCE_THRESHOLD and not m.void_reason]
            if light:
                reasons.append("Mark is light or not an X (tick / dot), please look: " + ", ".join(light))

        paper_no = read_paper_no(page.image)
        file_no = file_paper_no(path.name)  # img_<number>.jpg / .jpeg only, as in the counting system
        if file_no is not None:
            if not paper_no:
                reasons.append(f"Paper number could not be read from the box (file says {file_no})")
            elif not same_paper(file_no, paper_no):
                reasons.append(f"File number {file_no} does not match paper number {paper_no}")
        elif not paper_no:
            reasons.append("Paper number could not be read from the box")
        sheets.append(Sheet(path.name, page_no, len(pages), paper_no, counted, len(touched) - len(counted), reasons))
    return sheets


def flag_duplicates(sheets: list[Sheet]) -> None:
    by_number: dict[int, list[Sheet]] = defaultdict(list)
    for s in sheets:
        if s.paper_no and s.paper_no.isdigit():
            by_number[int(s.paper_no)].append(s)
    for same in by_number.values():
        if len(same) > 1:
            for s in same:
                others = ", ".join(o.label for o in same if o is not s)
                s.reasons.append(f"Same paper number {s.number} also on {others}: scanned twice or photocopy?")


# ---------------------------------------------------------------- results
def rank_post(post: Post, votes: dict[int, int], ballots: int) -> list[dict]:
    """Candidates of a post, best first, with rank and outcome ('elected' / 'tie' / '').
    Same rule as the counting system: the top `seats` with at least one vote are
    elected; a tie across the last seat marks everybody in it 'tie'."""
    cands = sorted(post.candidates, key=lambda c: (-votes[c.id], c.order, c.id))
    ranks, previous, rank = [], None, 0
    for index, c in enumerate(cands, start=1):
        if votes[c.id] != previous:
            rank, previous = index, votes[c.id]
        ranks.append(rank)
    seats = post.seats
    outcomes = [""] * len(cands)
    if seats < len(cands) and cands:
        cutoff = votes[cands[seats - 1].id]
        boundary_tie = votes[cands[seats].id] == cutoff
    else:
        cutoff, boundary_tie = None, False
    for i, c in enumerate(cands[:seats]):
        if votes[c.id] == 0:
            continue
        outcomes[i] = "tie" if boundary_tie and votes[c.id] == cutoff else "elected"
    if boundary_tie and cutoff:
        for i in range(seats, len(cands)):
            if votes[cands[i].id] == cutoff:
                outcomes[i] = "tie"
    return [
        {"c": c, "votes": votes[c.id], "pct": (votes[c.id] / ballots * 100) if ballots else 0.0,
         "rank": ranks[i], "outcome": outcomes[i]}
        for i, c in enumerate(cands)
    ]


# ------------------------------------------------------------------- html
CSS = r"""
html, body { margin: 0; padding: 0; background: #fff; }
.rpt-sheet {
  --ink: #000; --ink-soft: #3a3a3a; --rule: #9c9c9c; --rule-strong: #000; --navy: #000; --gold: #000;
  --gold-soft: #dcdcdc; --zebra: #f1f1f1;
  --rpt-bn-font: 'Noto Sans Bengali', 'Nirmala UI', 'Vrinda', 'Kalpurush', sans-serif;
  --mono: 'JetBrains Mono', Consolas, monospace;
  color: var(--ink); background: #fff; font-family: 'Plus Jakarta Sans', 'Segoe UI', Arial, sans-serif;
  font-size: 10pt; line-height: 1.35; -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.rpt-bn { font-family: var(--rpt-bn-font); }
.rpt-sheet .mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.rpt-sheet .num { text-align: center; }
.rpt-sheet .strong { font-weight: 800; }
.rpt-muted { color: var(--ink-soft); font-style: italic; }

.rpt-head { margin-bottom: 4mm; }
.rpt-letterhead { display: grid; grid-template-columns: 22mm 1fr 34mm; align-items: center; gap: 5mm; padding-bottom: 3mm; border-bottom: 3px solid #000; position: relative; }
.rpt-letterhead::after { content: ""; position: absolute; left: 0; right: 0; bottom: -6px; border-bottom: 1px solid #000; }
.rpt-logo { width: 22mm; height: 22mm; object-fit: contain; filter: grayscale(1) contrast(1.15); }
.rpt-org { text-align: center; }
.rpt-org-bn { font-size: 16pt; font-weight: 700; line-height: 1.25; }
.rpt-org-en { font-size: 10pt; font-weight: 800; letter-spacing: 0.22em; text-transform: uppercase; }
.rpt-election { margin-top: 1.5mm; display: flex; flex-direction: column; font-size: 10pt; color: var(--ink-soft); }
.rpt-election .rpt-bn { font-size: 11.5pt; font-weight: 600; color: var(--ink); }
.rpt-stamp { justify-self: end; text-align: center; padding: 2mm 3mm; border: 1.5px solid #000; color: #000; background: #fff; font-weight: 900; letter-spacing: 0.18em; text-transform: uppercase; font-size: 10pt; }
.rpt-stamp small { display: block; font-size: 6.5pt; letter-spacing: 0.08em; font-weight: 700; }
.rpt-title-band { margin-top: 4mm; padding: 1mm 0 2.2mm; border-bottom: 0.75px solid #000; display: flex; flex-direction: column; align-items: center; gap: 1mm; text-align: center; }
.rpt-title-band h1 { margin: 0; font-size: 14pt; font-weight: 800; letter-spacing: 0.14em; text-transform: uppercase; }
.rpt-title-band h1 .rpt-bn { font-weight: 600; font-size: 12.5pt; letter-spacing: 0; text-transform: none; }
.rpt-meta { display: flex; flex-wrap: wrap; justify-content: center; gap: 1mm 6mm; font-size: 8.5pt; color: var(--ink-soft); }
.rpt-meta b { color: #000; }

.rpt-figures { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; border-top: 1.5px solid #000; border-bottom: 1.5px solid #000; margin: 3mm 0; }
.rpt-figure { padding: 2mm 1.5mm; text-align: center; border-left: 1px solid var(--rule); }
.rpt-figure:first-child { border-left: 0; }
.rpt-figure b { display: block; font-size: 14pt; font-weight: 800; font-variant-numeric: tabular-nums; }
.rpt-figure span { display: block; font-size: 7pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-soft); }
.rpt-h2 { font-size: 10.5pt; font-weight: 800; text-transform: uppercase; letter-spacing: 0.08em; margin: 4mm 0 2mm; padding-left: 2.5mm; border-left: 3px solid #000; break-after: avoid; }
.rpt-note { font-size: 8pt; color: var(--ink-soft); margin: 2mm 0; }
.rpt-note.is-warn { color: #000; font-weight: 600; background: var(--zebra); border: 1px solid #000; border-left-width: 4px; padding: 1.5mm 2.5mm; }

.rpt-table { width: 100%; border-collapse: collapse; font-size: 9pt; border: 1px solid #000; }
.rpt-table th { background: #fff; color: #000; border-top: 1.5px solid #000; border-bottom: 1.5px solid #000; font-size: 7.5pt; font-weight: 800; text-transform: uppercase; letter-spacing: 0.07em; padding: 1.8mm 2mm; text-align: left; }
.rpt-table th.num { text-align: center; }
.rpt-table td { padding: 1.4mm 2mm; border-bottom: 1px solid var(--rule); vertical-align: middle; }
.rpt-table thead { display: table-header-group; }
.rpt-table tr { break-inside: avoid; }
.rpt-post-no { font-weight: 800; font-family: var(--mono); }
.rpt-post-en { display: block; font-size: 7.5pt; color: var(--ink-soft); text-transform: uppercase; letter-spacing: 0.05em; }

.rpt-winners { table-layout: fixed; }
.rpt-winners .rpt-group-start td { border-top: 1.5px solid var(--rule-strong); }
.rpt-winners tbody tr:first-child td { border-top: 0; }
.rpt-winner-name { display: flex; align-items: center; gap: 2mm; font-weight: 700; line-height: 1.2; }
.rpt-tick { display: inline-grid; place-items: center; width: 4.2mm; height: 4.2mm; border-radius: 50%; background: #fff; color: #000; border: 1px solid #000; font-size: 7pt; font-weight: 900; flex: none; }
.rpt-tie { font-weight: 700; font-style: italic; font-size: 8.5pt; background: var(--zebra); white-space: normal !important; }
.rpt-winners td { padding-top: 0.7mm; padding-bottom: 0.7mm; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rpt-winners .rpt-bn { font-weight: 700; margin-right: 1.5mm; }
.rpt-winners .rpt-post-en { display: inline; font-size: 6pt; }
.rpt-winner-name > span:last-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.rpt-annex { break-before: page; }
.rpt-all { table-layout: fixed; font-size: 8.5pt; }
.rpt-all td { padding: 0.7mm 1.6mm; }
.rpt-all .rpt-post-en { font-size: 6.5pt; }
.rpt-all-post { break-inside: avoid; }
.rpt-all-post tr:first-child td { border-top: 1.5px solid var(--rule-strong); }
.rpt-all-postname { background: #fafafa; }
.rpt-post-seats-inline { display: block; font-size: 7pt; color: var(--ink-soft); font-weight: 700; margin-top: 0.5mm; }
.rpt-all-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rpt-all-name .rpt-bn { font-weight: 600; margin-right: 1.5mm; }
.rpt-name-en-inline { font-size: 7.5pt; color: var(--ink-soft); }
.rpt-all tr.is-elected td:not([rowspan]) { background: #e2e2e2; font-weight: 800; }
.rpt-all tr.is-elected .rpt-result { font-weight: 900; letter-spacing: 0.06em; }
.rpt-all tr.is-tie td:not([rowspan]) { background: var(--zebra); font-style: italic; }
.rpt-all tr.is-tie .rpt-result { font-weight: 900; text-decoration: underline; }

.rpt-tally { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 7.5pt; font-variant-numeric: tabular-nums; margin: 4mm auto 0; border: 1.5px solid #000; }
.rpt-col-sl { width: 7mm; } .rpt-col-no { width: 13mm; } .rpt-col-file { width: 30mm; } .rpt-col-cand { width: 6.2mm; }
.rpt-col-total { width: 9mm; } .rpt-col-remark { width: 13mm; }
.rpt-tally thead { display: table-header-group; }
.rpt-tally tr { break-inside: avoid; }
.rpt-tally th, .rpt-tally td { border: 1px solid var(--rule); text-align: center; padding: 0.5mm 0.3mm; overflow: hidden; }
.rpt-tally th { background: #fff; color: #000; font-weight: 700; border-color: #000; }
.rpt-tally .grp { border-left: 1.6px solid var(--rule-strong); }
.rpt-tally-post { padding: 1mm 0.6mm !important; vertical-align: top; }
.rpt-tally-post-no { display: block; font-weight: 800; font-family: var(--mono); font-size: 7pt; }
.rpt-tally-post-name { font-family: var(--rpt-bn-font); font-weight: 600; font-size: 6pt; line-height: 1.15; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow-wrap: anywhere; }
.rpt-tally-cand { vertical-align: bottom; padding: 1mm 0.4mm !important; }
.rpt-tally-vno { display: block; margin-top: 0.8mm; font-family: var(--mono); font-weight: 700; font-size: 6pt; letter-spacing: -0.02em; }
.rpt-tally-cname { display: block; height: 27mm; margin: 0 auto; writing-mode: vertical-rl; transform: rotate(180deg); text-align: left; font-family: var(--rpt-bn-font); font-weight: 500; font-size: 6.5pt; line-height: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rpt-tally td.rpt-tally-sl { color: var(--ink-soft); }
.rpt-tally td.rpt-tally-no { font-family: var(--mono); font-weight: 700; white-space: nowrap; }
.rpt-tally td.rpt-tally-file { text-align: left; padding-left: 1mm; font-size: 6.5pt; white-space: nowrap; text-overflow: ellipsis; }
.rpt-tally-total { font-weight: 800; }
.rpt-tally th.rpt-tally-total, .rpt-tally th.rpt-tally-remark, .rpt-tally th.rpt-tally-sl, .rpt-tally th.rpt-tally-no, .rpt-tally th.rpt-tally-file { font-size: 6.5pt; text-transform: uppercase; letter-spacing: 0.04em; }
.rpt-tally td.rpt-tally-total { border-left: 1.6px solid var(--rule-strong); background: var(--zebra); }
.rpt-tally-remark { font-size: 6.5pt; }
.rpt-tally tr.is-review td.rpt-tally-remark { font-weight: 700; }
.rpt-tally td.one { font-weight: 800; background: var(--gold-soft); }
.rpt-tally td.zero { color: #a6a6a6; }
.rpt-tally tbody tr:nth-child(even) td.zero { background: var(--zebra); }
.rpt-tally tbody tr:nth-child(5n) td { border-bottom-color: #4d4d4d; }
.rpt-tally-sum td { border-top: 2.5px double var(--rule-strong); font-weight: 800; font-size: 8.5pt; background: #ececec; padding: 1.2mm 0.6mm; }
.rpt-tally-sum td:first-child { text-transform: uppercase; letter-spacing: 0.08em; font-size: 7pt; }
.rpt-tally-sum td.is-elected { background: #d6d6d6; font-weight: 900; box-shadow: inset 0 0 0 1.2px #000; }
.rpt-tally-sum td.is-tie { text-decoration: underline 1.5px; text-underline-offset: 2px; background: #fff; font-style: italic; }
.rpt-tally-empty { padding: 6mm !important; }

.rpt-check { font-size: 8.5pt; }
.rpt-check td { padding: 1mm 2mm; vertical-align: top; }
.rpt-check td.file { word-break: break-all; }
.rpt-check ul { margin: 0; padding-left: 4mm; }

.rpt-sign { margin-top: 5mm; break-inside: avoid; }
.rpt-sign.is-compact { margin-top: 3mm; }
.rpt-sign.is-compact .rpt-certify { margin-bottom: 4mm; padding: 1.5mm 3mm; font-size: 8.5pt; }
.rpt-sign.is-compact .rpt-sign-line { height: 8mm; }
.rpt-certify { font-size: 9pt; margin: 0 0 4mm; padding: 2.5mm 3.5mm; border: 1px solid #000; border-left-width: 4px; background: #fff; }
.rpt-sign-row { display: grid; gap: 10mm; }
.rpt-sign-box { font-size: 8.5pt; }
.rpt-sign-line { border-bottom: 1px solid var(--ink); height: 10mm; margin-bottom: 1.5mm; }
.rpt-sign-role { font-weight: 800; }
.rpt-sign-field { color: var(--ink-soft); margin-top: 1.6mm; border-bottom: 1px dotted #6b6b6b; padding-bottom: 0.5mm; }
"""


def bn_digits(value) -> str:
    return "".join(BN_DIGITS[int(ch)] if ch.isdigit() else ch for ch in str(value))


def bn_ordinal(n: int) -> str:
    suffix = {1: "ম", 2: "য়", 3: "য়", 4: "র্থ", 5: "ম", 6: "ষ্ঠ", 7: "ম", 8: "ম", 9: "ম", 10: "ম"}
    return bn_digits(n) + suffix.get(n, "তম")


def en_ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


TITLE_BN = f"আইসিবি কর্মকর্তা সমিতির {bn_ordinal(COUNCIL_NO)} কার্যনির্বাহী পরিষদ নির্বাচন-{bn_digits(ELECTION_YEAR)}"
TITLE_EN = f"ICB Officers' Association {en_ordinal(COUNCIL_NO)} Executive Council Election {ELECTION_YEAR}"
TITLES = {"summary": ("Result Summary", "ফলাফল সারসংক্ষেপ"), "tally": ("Ballot-wise Vote Tally", "ব্যালট-ভিত্তিক ভোট গণনা")}


def plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def logo_src() -> str:
    logo = HERE / "rs_engine" / "icb-logo.png"
    if not logo.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(logo.read_bytes()).decode("ascii")


def sheet_header(kind: str, stamp: str, extra: str = "") -> str:
    en, bn = TITLES[kind]
    logo = logo_src()
    return f"""
<header class="rpt-head">
  <div class="rpt-letterhead">
    {f'<img class="rpt-logo" src="{logo}" alt="">' if logo else '<span></span>'}
    <div class="rpt-org">
      <div class="rpt-org-bn rpt-bn">আইসিবি কর্মকর্তা সমিতি</div>
      <div class="rpt-org-en">ICB Officers' Association</div>
      <div class="rpt-election"><span class="rpt-bn">{e(TITLE_BN)}</span><span>{e(TITLE_EN)}</span></div>
    </div>
    <div class="rpt-stamp">Provisional<small>read by the scanner</small></div>
  </div>
  <div class="rpt-title-band">
    <h1>{en} <span class="rpt-bn">· {bn}</span></h1>
    <div class="rpt-meta"><span>Election year <b>{ELECTION_YEAR}</b></span><span>Prepared <b>{e(stamp)}</b></span>{extra}</div>
  </div>
</header>"""


def signatures(statement: str, compact: bool = False) -> str:
    boxes = "".join(
        f'<div class="rpt-sign-box"><div class="rpt-sign-line"></div><div class="rpt-sign-role">{e(role) or "&nbsp;"}</div>'
        '<div class="rpt-sign-field">Name:</div><div class="rpt-sign-field">Date:</div></div>'
        for role in SIGNATORIES
    )
    return (f'<section class="rpt-sign {"is-compact" if compact else ""}"><p class="rpt-certify">{statement}</p>'
            f'<div class="rpt-sign-row" style="grid-template-columns: repeat({max(1, len(SIGNATORIES))}, 1fr)">{boxes}</div></section>')


def page(kind: str, size: str, body: str) -> str:
    footer = (f"{TITLES[kind][0]} · Election {ELECTION_YEAR}" if kind == "tally" else f"{TITLES[kind][0]} · {TITLE_EN}").replace('"', "")
    initials = (' @bottom-center { content: "Initials: ____________   ____________   ____________"; font: 8pt sans-serif; color: #555; white-space: nowrap; }'
                if kind == "tally" else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{TITLES[kind][0]}</title>
<style>
@page {{ size: {size}; margin: 12mm 11mm 14mm;
  @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font: 8pt sans-serif; color: #555; white-space: nowrap; }}
  @bottom-left {{ content: "{footer}"; font: 8pt sans-serif; color: #555; white-space: nowrap; }}{initials} }}
{CSS}
</style></head><body>{body}</body></html>"""


def post_name(p: Post) -> str:
    return (f'<span class="rpt-bn">{e(p.name_bn)}</span>' if p.name_bn else "") + f'<span class="rpt-post-en">{e(p.name_en)}</span>'


def cand_name(c: Candidate) -> str:
    bn = f'<span class="rpt-bn">{e(c.name_bn)}</span>' if c.name_bn else ""
    return bn + f'<span class="{"rpt-name-en-inline" if c.name_bn else ""}">{e(c.name_en)}</span>'


def summary_html(posts, ranked, sheets, unread, files_found, stamp) -> str:
    ballots = len(sheets)
    total_votes = sum(len(s.counted) for s in sheets)
    review = sum(1 for s in sheets if s.reasons)

    figures = []
    if REGISTERED_VOTERS:
        figures.append(("Registered voters", REGISTERED_VOTERS))
    figures += [("Files scanned", files_found), ("Ballots counted", ballots), ("To check by hand", review), ("Files not read", len(unread))]
    if REGISTERED_VOTERS:
        figures.append(("Turnout", f"{ballots / REGISTERED_VOTERS * 100:.2f}%"))
    figures.append(("Valid votes", total_votes))
    out = ['<article class="rpt-sheet rpt-summary">', sheet_header("summary", stamp), '<section class="rpt-figures">']
    out += [f'<div class="rpt-figure"><b>{value}</b><span>{label}</span></div>' for label, value in figures]
    out.append("</section>")
    if unread:
        n = len(unread)
        out.append(f'<p class="rpt-note is-warn">{n} scanned {plural(n, "file is", "files are")} not read and not in these totals: '
                   f'{plural(n, "it is", "they are")} listed at the end of the Ballot-wise Vote Tally and must be counted by hand.</p>')
    if review:
        out.append(f'<p class="rpt-note is-warn">{review} {plural(review, "ballot needs", "ballots need")} a look by hand (unclear mark, more marks than allowed, '
                   'paper number). They are included in these totals and listed at the end of the Ballot-wise Vote Tally: check them before signing.</p>')

    out.append('<h2 class="rpt-h2">A. Elected candidates</h2><table class="rpt-table rpt-winners">'
               '<colgroup><col style="width:7%"><col style="width:33%"><col style="width:6%"><col style="width:8%"><col><col style="width:7%"><col style="width:6%"></colgroup>'
               '<thead><tr><th class="num">Post</th><th>Post name</th><th class="num">Seats</th><th class="num">Voter No.</th>'
               '<th>Elected candidate</th><th class="num">Votes</th><th class="num">Lead</th></tr></thead><tbody>')
    ties = 0
    for p in posts:
        rows = ranked[p.no]
        elected = [r for r in rows if r["outcome"] == "elected"]
        tied = [r for r in rows if r["outcome"] == "tie"]
        ties += bool(tied)
        loser = next((r for r in rows if not r["outcome"]), None)
        span = (len(elected) + (1 if tied else 0)) or 1
        head = (f'<td class="num rpt-post-no" rowspan="{span}">{p.no:02d}</td><td rowspan="{span}">{post_name(p)}</td>'
                f'<td class="num" rowspan="{span}">{p.seats}</td>')
        for i, r in enumerate(elected):
            lead = f'+{r["votes"] - loser["votes"]}' if loser else "—"
            out.append(f'<tr class="{"rpt-group-start" if i == 0 else ""}">{head if i == 0 else ""}'
                       f'<td class="num mono">{e(r["c"].voter_no)}</td>'
                       f'<td><div class="rpt-winner-name"><span class="rpt-tick">✓</span><span>{cand_name(r["c"])}</span></div></td>'
                       f'<td class="num mono strong">{r["votes"]}</td><td class="num mono">{lead}</td></tr>')
        if tied:
            v = tied[0]["votes"]
            seat = "the last seat" if elected else (f"{p.seats} seats" if p.seats > 1 else "the seat")
            names = " and ".join(e(r["c"].name_bn or r["c"].name_en) for r in tied)
            out.append(f'<tr class="{"" if elected else "rpt-group-start"}">{"" if elected else head}'
                       f'<td class="num mono">{", ".join(e(r["c"].voter_no) for r in tied)}</td>'
                       f'<td class="rpt-tie" colspan="3">Tie on {v} {plural(v, "vote", "votes")} between <span class="rpt-bn">{names}</span> '
                       f'for {seat}: to be decided by the Election Commission</td></tr>')
        if not elected and not tied:
            out.append(f'<tr class="rpt-group-start"><td class="num rpt-post-no">{p.no:02d}</td><td>{post_name(p)}</td>'
                       f'<td class="num">{p.seats}</td><td class="rpt-muted" colspan="4">No votes counted for this post</td></tr>')
    out.append("</tbody></table>")

    of_voters = f" of <b>{REGISTERED_VOTERS}</b> registered voters" if REGISTERED_VOTERS else ""
    out.append(signatures(f"We certify that the results above were counted from <b>{ballots}</b> ballot papers{of_voters}. "
                          "The votes of every candidate are given in the annex."))

    out.append('<section class="rpt-annex"><h2 class="rpt-h2">Annex · B. Votes received by every candidate</h2>'
               '<table class="rpt-table rpt-all"><colgroup><col style="width:6%"><col style="width:19%"><col style="width:6%"><col style="width:8%"><col>'
               '<col style="width:7%"><col style="width:9%"><col style="width:10%"></colgroup>'
               '<thead><tr><th class="num">Post</th><th>Post name</th><th class="num">Rank</th><th class="num">Voter No.</th><th>Candidate</th>'
               '<th class="num">Votes</th><th class="num">% of ballots</th><th class="num">Result</th></tr></thead>')
    for p in posts:
        rows = ranked[p.no]
        post_votes = sum(r["votes"] for r in rows)
        out.append('<tbody class="rpt-all-post">')
        for i, r in enumerate(rows):
            first = (f'<td class="num rpt-post-no" rowspan="{len(rows)}">{p.no:02d}</td><td rowspan="{len(rows)}" class="rpt-all-postname">{post_name(p)}'
                     f'<span class="rpt-post-seats-inline">{f"{p.seats} seats" if p.seats > 1 else "1 seat"} · {post_votes} votes</span></td>') if i == 0 else ""
            result = {"elected": "ELECTED", "tie": "TIE"}.get(r["outcome"], "")
            out.append(f'<tr class="{("is-" + r["outcome"]) if r["outcome"] else ""}">{first}<td class="num">{r["rank"]}</td>'
                       f'<td class="num mono">{e(r["c"].voter_no)}</td><td class="rpt-all-name">{cand_name(r["c"])}</td>'
                       f'<td class="num mono strong">{r["votes"]}</td><td class="num mono">{r["pct"]:.2f}</td><td class="num rpt-result">{result}</td></tr>')
        out.append("</tbody>")
    out.append("</table>")
    if ties:
        out.append('<p class="rpt-note">TIE: equal votes for the last seat of a post; the Election Commission decides as per the constitution.</p>')
    n_cands = sum(len(p.candidates) for p in posts)
    out.append(signatures(f"Annex to the Result Summary: votes received by each of the {n_cands} candidates.", compact=True))
    out.append("</section></article>")
    return page("summary", "A4 portrait", "".join(out))


def tally_html(posts, ranked, sheets, unread, stamp) -> str:
    columns = [c for p in posts for c in p.candidates]  # ballot order
    outcome = {r["c"].id: r["outcome"] for rows in ranked.values() for r in rows}
    totals: dict[int, int] = defaultdict(int)
    for s in sheets:
        for cid in s.counted:
            totals[cid] += 1
    grand = sum(totals.values())
    void = sum(s.void_marks for s in sheets)
    first_of_post = {p.candidates[0].id for p in posts}
    grp = lambda c: "grp" if c.id in first_of_post else ""  # noqa: E731

    extra = f"<span>1 = vote counted · 0 = no vote · <b>{len(sheets)}</b> ballots × <b>{len(columns)}</b> candidates</span>"
    out = ['<article class="rpt-sheet rpt-tally-sheet">', sheet_header("tally", stamp, extra), '<table class="rpt-tally"><colgroup>',
           '<col class="rpt-col-sl"><col class="rpt-col-no"><col class="rpt-col-file">', '<col class="rpt-col-cand">' * len(columns),
           '<col class="rpt-col-total"><col class="rpt-col-remark"></colgroup><thead><tr class="rpt-tally-posts">',
           '<th rowspan="2" class="rpt-tally-sl">Sl.</th><th rowspan="2" class="rpt-tally-no">Ballot<br>No.</th><th rowspan="2" class="rpt-tally-file">Scanned file</th>']
    for p in posts:
        out.append(f'<th colspan="{len(p.candidates)}" class="rpt-tally-post grp"><span class="rpt-tally-post-no">{p.no:02d}</span>'
                   f'<span class="rpt-tally-post-name">{e(p.name_bn or p.name_en)}</span></th>')
    out.append('<th rowspan="2" class="rpt-tally-total">Votes</th><th rowspan="2" class="rpt-tally-remark">Remarks</th></tr><tr class="rpt-tally-cands">')
    for c in columns:
        out.append(f'<th class="rpt-tally-cand {grp(c)}"><span class="rpt-tally-cname">{e(c.name_bn or c.name_en)}</span>'
                   f'<span class="rpt-tally-vno">{e(c.voter_no)}</span></th>')
    out.append("</tr></thead><tbody>")
    for serial, s in enumerate(sheets, start=1):
        marks = set(s.counted)
        cells = "".join(f'<td class="{"one" if c.id in marks else "zero"} {grp(c)}">{1 if c.id in marks else 0}</td>' for c in columns)
        out.append(f'<tr class="{"is-review" if s.reasons else ""}"><td class="rpt-tally-sl">{serial}</td><td class="rpt-tally-no">{e(s.number)}</td>'
                   f'<td class="rpt-tally-file">{e(s.label)}</td>{cells}<td class="rpt-tally-total">{len(s.counted)}</td>'
                   f'<td class="rpt-tally-remark">{"Check" if s.reasons else ""}</td></tr>')
    if not sheets:
        out.append(f'<tr><td colspan="{len(columns) + 5}" class="rpt-muted rpt-tally-empty">No ballots have been counted.</td></tr>')
    out.append('<tr class="rpt-tally-sum"><td colspan="3">Total</td>')
    out += [f'<td class="{grp(c)} {("is-" + outcome[c.id]) if outcome[c.id] else ""}">{totals[c.id]}</td>' for c in columns]
    out.append(f'<td class="rpt-tally-total">{grand}</td><td></td></tr></tbody></table>')
    note = ("Totals in a bold box on grey are the elected candidates (italic and underlined: tie for the last seat). "
            "Each candidate's total equals the votes in the Result Summary. Ballot No. = the number read from the box on the paper (? = not readable).")
    if void:
        note += f" {void} {plural(void, 'mark was', 'marks were')} not counted (more boxes marked than the post allows) and show as 0."
    out.append(f'<p class="rpt-note">{note}</p>')

    review = [(i, s) for i, s in enumerate(sheets, start=1) if s.reasons]
    if review:
        out.append(f'<h2 class="rpt-h2">Ballots to check by hand ({len(review)})</h2>'
                   '<p class="rpt-note">Remark "Check" in the tally. These ballots are in the totals as read by the scanner: compare each with its paper.</p>'
                   '<table class="rpt-table rpt-check"><colgroup><col style="width:6%"><col style="width:10%"><col style="width:22%"><col></colgroup>'
                   '<thead><tr><th class="num">Sl.</th><th class="num">Ballot No.</th><th>Scanned file</th><th>What to check</th></tr></thead><tbody>')
        for serial, s in review:
            items = "".join(f"<li>{e(r)}</li>" for r in s.reasons)
            out.append(f'<tr><td class="num">{serial}</td><td class="num mono strong">{e(s.number)}</td><td class="file">{e(s.label)}</td><td><ul>{items}</ul></td></tr>')
        out.append("</tbody></table>")
    if unread:
        out.append(f'<h2 class="rpt-h2">Files not read ({len(unread)})</h2>'
                   '<p class="rpt-note">Not in the tally and not in the totals: count these papers by hand.</p>'
                   '<table class="rpt-table rpt-check"><colgroup><col style="width:6%"><col style="width:32%"><col></colgroup>'
                   '<thead><tr><th class="num">No.</th><th>Scanned file</th><th>Reason</th></tr></thead><tbody>')
        for n, (name, reason) in enumerate(unread, start=1):
            out.append(f'<tr><td class="num">{n}</td><td class="file">{e(name)}</td><td>{e(reason)}</td></tr>')
        out.append("</tbody></table>")

    out.append(signatures(f"We certify that this tally lists every one of the <b>{len(sheets)}</b> counted ballot papers and the "
                          f"<b>{grand}</b> valid votes read from them."))
    out.append("</article>")
    return page("tally", "A4 landscape", "".join(out))


# -------------------------------------------------------------------- pdf
def find_browser() -> Path | None:
    """Microsoft Edge (part of Windows) or Chrome: used without a window to print the PDF."""
    import os
    roots = [os.environ.get(k, "") for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    for sub in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
        for root in roots:
            if root and (Path(root) / sub).exists():
                return Path(root) / sub
    for name in ("msedge", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def write_pdf(browser: Path | None, name: str, document: str, work: Path) -> Path:
    """Print `document` to OUTPUT_DIR/<name>.pdf.  Without a browser the HTML itself is saved."""
    source = work / f"{name}.html"
    source.write_text(document, encoding="utf-8")
    if browser is None:
        target = OUTPUT_DIR / f"{name}.html"
        shutil.copyfile(source, target)
        return target
    printed = work / f"{name}.pdf"
    subprocess.run(
        [str(browser), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
         f"--user-data-dir={work / 'profile'}", "--no-pdf-header-footer", f"--print-to-pdf={printed}", source.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300, check=False,
    )
    if not printed.exists() or printed.stat().st_size == 0:
        raise RuntimeError(f"{browser.name} did not write the PDF")
    target = OUTPUT_DIR / f"{name}.pdf"
    try:
        shutil.copyfile(printed, target)
    except PermissionError:  # the old report is open in a PDF viewer
        target = OUTPUT_DIR / f"{name} ({datetime.now():%H%M%S}).pdf"
        shutil.copyfile(printed, target)
    return target


# ------------------------------------------------------------------- main
def ask_folder() -> Path:
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1].strip().strip('"'))
        if not folder.is_dir():
            raise SystemExit(f"Folder not found: {folder}")
        return folder
    while True:
        try:
            answer = input(f"Folder of the scanned ballots (images / PDFs)\n[Enter = {HERE}]: ").strip().strip('"').strip("'")
        except EOFError:
            answer = ""
        folder = Path(answer) if answer else HERE
        if folder.is_dir():
            return folder
        print(f"  Folder not found: {folder}\n")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    print("ICB Officers' Association - ballot folder scan (RS)")
    print("=" * 60)
    posts, layout, seats = load_candidates(CANDIDATES_CSV)
    by_post = {p.no: p for p in posts}
    names = {c.id: f"{c.voter_no} {c.name_en}" for p in posts for c in p.candidates}
    print(f"Candidates: {len(layout)} in {len(posts)} posts  ({CANDIDATES_CSV.name})")

    folder = ask_folder()
    files = scan_files(folder)
    print(f"\nFolder: {folder}\nFiles to read: {len(files)}\n")
    if not files:
        print("No image or PDF file in this folder - nothing to report.")
        return 1

    sheets: list[Sheet] = []
    unread: list[tuple[str, str]] = []
    started = time.time()
    for index, path in enumerate(files, start=1):
        try:
            read = read_file(path, layout, seats, names, by_post)
        except Exception as exc:
            reason = "not a readable image" if type(exc).__name__ == "UnidentifiedImageError" else (f"{exc}" or type(exc).__name__)
            unread.append((path.name, reason))
            print(f"[{index:>4}/{len(files)}] {path.name:<32} NOT READ: {reason}")
            continue
        sheets.extend(read)
        for s in read:
            flag = "CHECK" if s.reasons else "ok"
            print(f"[{index:>4}/{len(files)}] {s.label:<32} paper {s.number:<7} votes {len(s.counted):>2}  {flag}")
    flag_duplicates(sheets)

    votes: dict[int, int] = defaultdict(int)
    for s in sheets:
        for cid in s.counted:
            votes[cid] += 1
    ranked = {p.no: rank_post(p, votes, len(sheets)) for p in posts}
    stamp = datetime.now().strftime("%d %B %Y, %I:%M %p").lstrip("0").replace(", 0", ", ").replace("AM", "am").replace("PM", "pm")

    browser = find_browser()
    if browser is None:
        print("\nMicrosoft Edge / Chrome not found: the reports are saved as HTML (open and print to PDF).")
    with tempfile.TemporaryDirectory(prefix="icb-rs-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        written = [
            write_pdf(browser, SUMMARY_NAME, summary_html(posts, ranked, sheets, unread, len(files), stamp), work),
            write_pdf(browser, TALLY_NAME, tally_html(posts, ranked, sheets, unread, stamp), work),
        ]

    review = sum(1 for s in sheets if s.reasons)
    print("\n" + "=" * 60)
    print(f"Files read      : {len(files) - len(unread)} of {len(files)}   ({time.time() - started:.0f} s)")
    print(f"Ballots counted : {len(sheets)}")
    print(f"Valid votes     : {sum(votes.values())}")
    print(f"To check by hand: {review}")
    print(f"Files not read  : {len(unread)}")
    print("\nReports:")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
