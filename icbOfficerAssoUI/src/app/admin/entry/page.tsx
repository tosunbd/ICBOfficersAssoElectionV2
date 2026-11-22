"use client";

import "../../entry.css";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import type { Candidate, Correction, Desk, EntryBallot, EntryState, Position } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import { useLoader } from "@/hooks/useLoader";
import { useToast } from "@/components/ui/Toast";
import { ConfirmDialog, Modal } from "@/components/ui/Modal";
import { Alert, CardHead, EmptyState, PageHeader, Spinner } from "@/components/ui/Basics";
import { Icon } from "@/components/ui/Icon";
import { BallotPaper, buildRows, checkBallot, sideIds, type Side } from "@/components/entry/BallotPaper";

const FALLBACK_TITLE = "আইসিবি কর্মকর্তা সমিতির কার্যনির্বাহী পরিষদ নির্বাচন";

export default function EntryPage() {
  return <Suspense fallback={<Spinner label="Loading…" />}><EntryScreen /></Suspense>;
}

function EntryScreen() {
  const { isEc, isLoading } = useAuth();
  if (isLoading) return <Spinner label="Loading…" />;
  return isEc ? <EntryDesk /> : <EntryMonitor />;
}

/* ------------------------------------------------------------------ */
/*  shared                                                             */
/* ------------------------------------------------------------------ */

/** The ballot of the active election: posts, candidates and the rows of the paper. */
function useBallotLayout(electionId: number | null) {
  const [layout, setLayout] = useState<{ electionId: number; positions: Position[]; candidates: Candidate[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!electionId) return;
    let cancelled = false;
    Promise.all([api.elections.get(electionId), api.candidates.list(electionId)])
      .then(([election, candidates]) => { if (!cancelled) setLayout({ electionId, positions: election.positions, candidates }); })
      .catch((err) => { if (!cancelled) setError(errorMessage(err, "The ballot could not be loaded")); });
    return () => { cancelled = true; };
  }, [electionId]);
  const current = layout && layout.electionId === electionId ? layout : null;
  const rows = useMemo(() => (current ? buildRows(current.positions, current.candidates) : []), [current]);
  return { positions: current?.positions ?? [], candidates: current?.candidates ?? [], rows, ready: current !== null, error };
}

function percent(desk: Pick<Desk, "entered" | "total">): number {
  return desk.total ? Math.round((desk.entered / desk.total) * 1000) / 10 : 0;
}

function rangeText(desk: Desk, digits: number): string {
  const pad = (n: number) => String(n).padStart(digits, "0");
  return `${pad(desk.ballot_from)} – ${pad(desk.ballot_to)}`;
}

function shortTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const sameIds = (a: Iterable<number>, b: Iterable<number>) =>
  Array.from(a).sort((x, y) => x - y).join(",") === Array.from(b).sort((x, y) => x - y).join(",");

/** What the rules made of the ballot on the paper. */
function TallyCard({ check }: { check: ReturnType<typeof checkBallot> }) {
  return (
    <>
      <div className="entry-tally">
        <div><strong>{check.marked}</strong><span>Marked</span></div>
        <div className="is-ok"><strong>{check.counted}</strong><span>Counted</span></div>
        <div className={check.nullIds.size ? "is-null" : ""}><strong>{check.nullIds.size}</strong><span>Null</span></div>
      </div>
      {check.nullPosts.length > 0 && (
        <div className="entry-nulls">
          {check.nullPosts.map((post) => (
            <div className="entry-null" key={post.position.id}>
              <Icon name="ban" size={15} strokeWidth={2.2} />
              <span><b className="text-bengali">{post.position.name_bn ?? post.position.name_en}</b>: {post.marked} marked, only {post.position.max_selections} allowed. Null vote for this post.</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function RecentList({ ballots, activeNo, onPick, empty, showDesk }: {
  ballots: EntryBallot[]; activeNo: number | null; onPick: (ballot: EntryBallot) => void; empty: string; showDesk?: boolean;
}) {
  if (ballots.length === 0) return <div className="empty-inline" style={{ padding: "18px 8px" }}><Icon name="inbox" size={26} />{empty}</div>;
  return (
    <div className="entry-recent">
      {ballots.map((b) => (
        <button key={b.ballot_id} type="button" className={`entry-recent-item ${activeNo === b.ballot_no ? "is-active" : ""}`} onClick={() => onPick(b)}>
          <span className="entry-recent-no">{b.label}</span>
          <span className="entry-recent-meta">
            {showDesk && b.entered_by ? `${b.entered_by} · ` : ""}{shortTime(b.corrected_at ?? b.entered_at)}{b.status === "reviewed" ? " · corrected" : ""}
            {b.pending && <em className="entry-wait"> · correction awaits approval</em>}
          </span>
          <span className="entry-recent-votes">{b.counted} vote{b.counted === 1 ? "" : "s"}{b.null_marks > 0 && <em> · {b.null_marks} null</em>}</span>
          <Icon name="chevronRight" size={14} className="text-faint" />
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Election Commissioner: the entry desk                              */
/* ------------------------------------------------------------------ */

const draftKey = (username: string | null) => `icb-entry-draft-${username ?? ""}`;

function EntryDesk() {
  const { token, username, fullName } = useAuth();
  const toast = useToast();
  const [state, setState] = useState<EntryState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<EntryBallot | null>(null);
  const [recent, setRecent] = useState<EntryBallot[]>([]);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<"blank" | "null" | null>(null);
  const [findNo, setFindNo] = useState("");
  const restored = useRef(false);

  const desk = state?.desks.find((d) => d.username === state.me) ?? null;
  const digits = state?.digits ?? 3;
  const { positions, candidates, rows, ready, error: layoutError } = useBallotLayout(state?.election?.id ?? null);
  const currentNo = editing ? editing.ballot_no : desk?.next_ballot_no ?? null;
  const currentLabel = currentNo ? String(currentNo).padStart(digits, "0") : "";
  const check = useMemo(() => checkBallot(positions, candidates, selected), [positions, candidates, selected]);
  const paused = Boolean(state?.election?.counting_paused);

  const loadState = useCallback(async () => {
    if (!token) return;
    try {
      const next = await api.entry.state(token);
      setState(next);
      setLoadError(null);
      // a page refresh keeps the boxes ticked on the paper that was on the desk
      if (!restored.current) {
        restored.current = true;
        const mine = next.desks.find((d) => d.username === next.me);
        try {
          const saved = JSON.parse(sessionStorage.getItem(draftKey(next.me)) ?? "null") as { ballot_no: number; ids: number[] } | null;
          if (saved && mine && saved.ballot_no === mine.next_ballot_no && saved.ids.length) setSelected(new Set(saved.ids));
        } catch { /* no saved draft */ }
      }
    } catch (err) {
      setLoadError(errorMessage(err, "The server cannot be reached"));
    }
  }, [token]);

  const loadRecent = useCallback(async () => {
    if (!token) return;
    try {
      setRecent(await api.entry.recent(token, 10));
    } catch { /* the list is a convenience */ }
  }, [token]);

  const [myCorrections, setMyCorrections] = useState<Correction[]>([]);
  const loadCorrections = useCallback(async () => {
    if (!token) return;
    try {
      setMyCorrections((await api.entry.corrections(token, "all")).slice(0, 6));
    } catch { /* the next refresh tries again */ }
  }, [token]);

  useLoader(loadState, 4000);
  useLoader(loadRecent, 5000);       // also shows when the SA / Admin has decided on a correction
  useLoader(loadCorrections, 5000);

  // what is ticked right now: kept for a refresh, and shown live to the SA / Admin
  const selectedKey = useMemo(() => Array.from(selected).sort((a, b) => a - b).join(","), [selected]);
  useEffect(() => {
    if (!token || !currentNo) return;
    const ids = selectedKey ? selectedKey.split(",").map(Number) : [];
    if (!editing) {
      try { sessionStorage.setItem(draftKey(username), JSON.stringify({ ballot_no: currentNo, ids })); } catch { /* ignore */ }
    }
    const timer = setTimeout(() => { api.entry.draft(token, currentNo, ids, Boolean(editing)).catch(() => undefined); }, 350);
    return () => clearTimeout(timer);
  }, [token, username, currentNo, selectedKey, editing]);

  // leaving with ticked boxes: ask first
  useEffect(() => {
    if (selected.size === 0) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [selected.size]);

  const toggle = useCallback((id: number) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback((side: Side) => {
    const ids = sideIds(rows, side);
    setSelected((current) => {
      const next = new Set(current);
      const all = ids.every((id) => next.has(id));
      ids.forEach((id) => (all ? next.delete(id) : next.add(id)));
      return next;
    });
  }, [rows]);

  const save = async () => {
    if (!token || !currentNo) return;
    setConfirm(null);
    setBusy(true);
    try {
      const ids = Array.from(selected);
      const result = editing ? await api.entry.correct(token, editing.ballot_no, ids) : await api.entry.save(token, currentNo, ids);
      const b = result.ballot;
      toast.success(editing
        ? `Correction of ballot ${b.label} sent for approval. The totals change when the SA or the Admin approves it.`
        : `Ballot ${b.label} saved: ${b.counted} vote${b.counted === 1 ? "" : "s"} counted` +
          (b.null_marks ? `, ${b.null_marks} null mark${b.null_marks === 1 ? "" : "s"}` : "") +
          (b.candidate_ids.length === 0 ? " (blank ballot)" : ""));
      setSelected(new Set());
      setEditing(null);
      try { sessionStorage.removeItem(draftKey(username)); } catch { /* ignore */ }
      setState((old) => (old ? { ...old, desks: old.desks.map((d) => (d.username === result.desk.username ? result.desk : d)) } : old));
      window.scrollTo({ top: 0, behavior: "smooth" });
      void loadRecent();
      void loadState();
      void loadCorrections();
    } catch (err) {
      toast.error(errorMessage(err));
      if (err instanceof ApiError && (err.status === 409 || err.status === 404)) void loadState();
    } finally {
      setBusy(false);
    }
  };

  const requestSave = () => {
    if (busy || !currentNo || !ready || paused) return;
    if (check.nullPosts.length > 0) setConfirm("null");
    else if (selected.size === 0) setConfirm("blank");
    else void save();
  };

  // Ctrl + Enter saves; Enter confirms an open question
  const hotkey = useRef({ requestSave, save, confirm });
  useEffect(() => { hotkey.current = { requestSave, save, confirm }; });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Enter") return;
      if (hotkey.current.confirm) { event.preventDefault(); void hotkey.current.save(); }
      else if (event.ctrlKey || event.metaKey) { event.preventDefault(); hotkey.current.requestSave(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const startEdit = (ballot: EntryBallot) => {
    setEditing(ballot);
    // a correction that is already waiting is shown as it was sent, so it can be changed again
    setSelected(new Set(ballot.pending ? ballot.pending.candidate_ids : ballot.candidate_ids));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const withdraw = async () => {
    if (!token || !editing?.pending) return;
    setBusy(true);
    try {
      await api.entry.withdraw(token, editing.pending.id);
      toast.success(`Correction of ballot ${editing.label} withdrawn. The ballot stays as it was saved.`);
      setEditing(null);
      setSelected(new Set());
    } catch (err) {
      toast.error(errorMessage(err));
      if (err instanceof ApiError && err.status === 409) { setEditing(null); setSelected(new Set()); }  // already decided meanwhile
    } finally {
      setBusy(false);
      void loadRecent();
      void loadState();
      void loadCorrections();
    }
  };

  const cancelEdit = () => {
    setEditing(null);
    setSelected(new Set());
  };

  const find = async (event: FormEvent) => {
    event.preventDefault();
    const number = Number(findNo);
    if (!token || !Number.isInteger(number) || number < 1) return;
    try {
      startEdit(await api.entry.get(token, number));
      setFindNo("");
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  if (!state) return loadError ? <Alert type="error">{loadError}</Alert> : <Spinner label="Opening your desk…" />;
  if (!state.election) {
    return <EmptyState icon="landmark" title="No election is active"><p>The Admin has to set the election to <strong>active</strong> before ballots can be entered.</p></EmptyState>;
  }
  if (!desk) {
    return <EmptyState icon="ban" title="No ballot range"><p>Your account has no ballot numbers assigned. Ask the Super Admin.</p></EmptyState>;
  }

  const done = desk.next_ballot_no === null;
  // a correction can be sent when the ticks differ from the saved ballot and from a request that is already waiting
  const edited = editing !== null && !sameIds(selected, editing.candidate_ids) && !(editing.pending && sameIds(selected, editing.pending.candidate_ids));

  return (
    <div className="page">
      <PageHeader eyebrow={`${desk.username} · ${fullName ?? desk.full_name ?? "Election Commissioner"}`} title="Ballot entry"
        subtitle={`Your ballots: ${rangeText(desk, digits)}. Tick what is marked on the paper, then save: the next ballot comes by itself.`} />

      {loadError && <Alert type="error">Connection problem: {loadError}. Your ticks stay on the form; saving works again when the server answers.</Alert>}
      {layoutError && <Alert type="error">{layoutError}</Alert>}
      {paused && <Alert type="warning"><strong>Counting is paused by the election commission.</strong> Saving is possible again after START. What you have ticked stays on the form.</Alert>}

      <div className="entry-layout">
        <div className="entry-paper-col">
          {editing && (
            <div className="entry-banner is-edit">
              <Icon name="edit" size={20} />
              <div className="flex-1">Correcting ballot {editing.label}{editing.pending ? " · a correction is waiting for approval" : ""}
                <small>
                  {editing.pending
                    ? `Sent ${formatDateTime(editing.pending.requested_at)}. The form shows the correction as it was sent; change it and send it again, or withdraw it.`
                    : `Saved ${formatDateTime(editing.corrected_at ?? editing.entered_at)}. Change the ticks and send the correction.`}
                  {" "}The ballot and the totals stay as they are until the SA or the Admin approves.
                </small>
              </div>
              {editing.pending && <button className="btn btn-danger-ghost btn-sm" onClick={withdraw} disabled={busy}><Icon name="x" size={14} /> Withdraw</button>}
              <button className="btn btn-ghost btn-sm" onClick={cancelEdit} disabled={busy}><Icon name="undo" size={14} /> Back to {done ? "the desk" : `ballot ${desk.next_label}`}</button>
            </div>
          )}
          {!editing && done && (
            <div className="entry-banner is-done">
              <Icon name="checkCircle" size={22} />
              <div className="flex-1">All {desk.total} ballots of your range are entered
                <small>{rangeText(desk, digits)} is complete. A saved ballot can still be corrected from the list on the right.</small>
              </div>
            </div>
          )}
          {!ready ? <Spinner label="Loading the ballot…" /> : (editing || !done) && (
            <BallotPaper
              titleBn={state.election.title_bn ?? FALLBACK_TITLE}
              ballotLabel={currentLabel}
              rows={rows} selected={selected} nullIds={check.nullIds}
              onToggle={toggle} onSelectAll={selectAll}
              flashKey={`${editing ? "edit" : "new"}-${currentNo}`}
            />
          )}
        </div>

        <aside className="entry-side">
          <div className="card card-gold">
            <div className="entry-now">
              <div>
                <div className="entry-now-label">{editing ? "Correcting ballot" : done ? "Range complete" : "Now entering ballot"}</div>
                <div className="entry-now-no">{currentLabel || "✓"}</div>
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700 }}>{desk.username}</div>
                <div className="entry-now-sub">Ballots {rangeText(desk, digits)}</div>
              </div>
            </div>
            <div className="entry-progress" aria-label="Progress of your range"><span style={{ width: `${percent(desk)}%` }} /></div>
            <div className="entry-progress-meta"><span><strong>{desk.entered}</strong> of {desk.total} entered</span><span>{desk.total - desk.entered} to go</span></div>
          </div>

          {(editing || !done) && (
            <div className="card">
              <CardHead icon="vote" title="This ballot" subtitle="As the counting rules read it" />
              <TallyCard check={check} />
              <div className="entry-actions">
                <button className="btn btn-success btn-lg entry-save" onClick={requestSave} disabled={busy || !ready || paused || (editing !== null && !edited)}>
                  {busy ? <><span className="btn-spinner" /> Saving…</>
                    : editing ? <><Icon name="shield" size={18} /> Send for approval</>
                    : <><Icon name="save" size={18} /> Save &amp; next ballot</>}
                </button>
                <button className="btn btn-ghost" onClick={() => setSelected(new Set(editing ? editing.candidate_ids : []))} disabled={busy || (editing ? sameIds(selected, editing.candidate_ids) : selected.size === 0)}>
                  <Icon name="undo" size={15} /> {editing ? "Reset to the saved ticks" : "Clear the form"}
                </button>
              </div>
              <p className="entry-hint">
                <kbd>Ctrl</kbd> + <kbd>Enter</kbd> saves. A paper with no mark is saved as a blank ballot: it is counted, with no vote for anyone.
                Several boxes of one post may be ticked, as on the paper: a post with more marks than allowed
                (1, or 3 for <span className="text-bengali">নির্বাহী সদস্য</span>) becomes a null vote.
                An unclear mark is still a vote (an X with a short or broken stroke, or strokes that do not meet in the middle): if the other box of that post is purely empty, tick the unclear one and it counts.
                Tick both only when the voter touched both boxes of the post; that vote is invalid.
                {editing && " A correction counts only after the SA or the Admin approves it."}
              </p>
            </div>
          )}

          <div className="card">
            <CardHead icon="scroll" title="Your saved ballots" subtitle="Click one to check it or to ask for a correction">
              {desk.pending_corrections > 0 && <span className="badge badge-warning">{desk.pending_corrections} awaiting approval</span>}
            </CardHead>
            <RecentList ballots={recent} activeNo={editing?.ballot_no ?? null} onPick={startEdit} empty="Nothing saved yet." />
            {myCorrections.length > 0 && (
              <div className="entry-corrections">
                <div className="entry-now-label" style={{ margin: "14px 0 6px" }}>Your corrections</div>
                {myCorrections.map((c) => (
                  <div key={c.id} className="entry-correction-row">
                    <span className="entry-recent-no">{c.label}</span>
                    <span className="entry-recent-meta">
                      {c.status === "pending" ? `sent ${shortTime(c.requested_at)}` : `${c.status === "withdrawn" ? "by you" : `by ${c.decided_by ?? "—"}`} ${shortTime(c.decided_at)}`}
                    </span>
                    <span className={`badge ${c.status === "approved" ? "badge-success" : c.status === "rejected" ? "badge-error" : c.status === "pending" ? "badge-warning" : "badge-muted"}`}>
                      {c.status === "pending" ? "awaiting approval" : c.status}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <form className="entry-find" onSubmit={find} style={{ marginTop: 12 }}>
              <input className="input input-sm" inputMode="numeric" placeholder="Open ballot no." value={findNo} onChange={(e) => setFindNo(e.target.value.replace(/\D/g, ""))} aria-label="Ballot number to open" />
              <button className="btn btn-ghost btn-sm" type="submit" disabled={!findNo}><Icon name="search" size={14} /> Open</button>
            </form>
          </div>

          <div className="card">
            <CardHead icon="users" title="All desks" subtitle={`${state.total_entered} of ${state.total_ballots} ballots entered`} />
            <div className="desk-mini">
              {state.desks.map((d) => (
                <div key={d.username} className={`desk-mini-row ${d.username === desk.username ? "is-me" : ""}`}>
                  <b>{d.username}</b>
                  <div className="entry-progress"><span style={{ width: `${percent(d)}%` }} /></div>
                  <span>{d.entered}/{d.total}</span>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>

      <Modal open={confirm !== null} title={confirm === "blank" ? `${editing ? "Correct" : "Save"} ballot ${currentLabel} as a blank ballot?` : `Ballot ${currentLabel} has null votes`} onClose={() => setConfirm(null)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setConfirm(null)} disabled={busy}>Go back and check</button>
            <button className="btn btn-primary" onClick={() => void save()} disabled={busy} autoFocus>
              <Icon name="save" size={16} /> {editing ? "Yes, send it for approval" : "Yes, save it"} <span className="entry-kbd" style={{ marginLeft: 6 }}>Enter</span>
            </button>
          </>
        }>
        {confirm === "blank" ? (
          <div className="confirm-body">
            <span className="confirm-icon"><Icon name="info" size={22} /></span>
            <p style={{ paddingTop: 10 }}>No box is ticked: the voter did not vote for anyone. The ballot is <strong>counted as a ballot</strong>, with <strong>no vote for any candidate</strong>.</p>
          </div>
        ) : (
          <div>
            <p className="text-muted" style={{ marginBottom: 12 }}>These posts have more marks than allowed, so <strong>no vote is counted for them</strong>. The other posts count as usual. Save if the paper really is marked this way: the voter touched every one of these boxes. If only one box has a mark, even an unclear one, and the other is purely empty, go back and tick only that one: it counts.</p>
            <div className="entry-nulls" style={{ marginTop: 0 }}>
              {check.nullPosts.map((post) => (
                <div className="entry-null" key={post.position.id}>
                  <Icon name="ban" size={15} strokeWidth={2.2} />
                  <span><b className="text-bengali">{post.position.name_bn ?? post.position.name_en}</b>: {post.marked} marked, only {post.position.max_selections} allowed</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Super Admin / Admin: watch the three desks, edit a saved ballot    */
/* ------------------------------------------------------------------ */

function EntryMonitor() {
  const { token } = useAuth();
  const toast = useToast();
  const params = useSearchParams();
  const [state, setState] = useState<EntryState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deskName, setDeskName] = useState<string | null>(null);
  const [opened, setOpened] = useState<EntryBallot | null>(null);       // a saved ballot opened by number / from the list
  const [lastSaved, setLastSaved] = useState<EntryBallot | null>(null); // the selected desk's latest saved ballot
  const [recent, setRecent] = useState<EntryBallot[]>([]);
  const [findNo, setFindNo] = useState("");
  const [corrections, setCorrections] = useState<Correction[]>([]);
  const [reviewId, setReviewId] = useState<number | null>(null);         // the correction shown on the paper
  const [showSaved, setShowSaved] = useState(false);                     // ... as saved instead of as corrected
  const [decision, setDecision] = useState<{ item: Correction; approve: boolean } | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [edit, setEdit] = useState<{ ballotNo: number; ids: Set<number> } | null>(null);  // the opened ballot is being edited
  const [confirmEdit, setConfirmEdit] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);

  const digits = state?.digits ?? 3;
  const { positions, candidates, rows, ready, error: layoutError } = useBallotLayout(state?.election?.id ?? null);

  const loadCorrections = useCallback(async () => {
    if (!token) return;
    try {
      setCorrections(await api.entry.corrections(token, "pending"));
    } catch { /* the next refresh tries again */ }
  }, [token]);
  useLoader(loadCorrections, 2500);

  const decide = async () => {
    if (!token || !decision) return;
    setDeciding(true);
    try {
      const result = decision.approve ? await api.entry.approve(token, decision.item.id) : await api.entry.reject(token, decision.item.id);
      toast.success(decision.approve
        ? `Ballot ${result.ballot.label} corrected: ${result.ballot.counted} vote${result.ballot.counted === 1 ? "" : "s"} counted now. The dashboard is updated.`
        : `Correction of ballot ${result.ballot.label} rejected. The ballot stays as it was saved.`);
      setReviewId(null);
      setShowSaved(false);
      setOpened(result.ballot);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setDeciding(false);
      setDecision(null);
      void loadCorrections();
    }
  };

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setState(await api.entry.state(token));
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err, "The server cannot be reached"));
    }
  }, [token]);

  useLoader(load, 1500);

  const open = useCallback(async (ballotNo: number, startEditing = false) => {
    if (!token) return;
    try {
      const ballot = await api.entry.get(token, ballotNo);
      setOpened(ballot);
      setReviewId(null);
      setEdit(startEditing ? { ballotNo: ballot.ballot_no, ids: new Set(ballot.candidate_ids) } : null);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }, [token, toast]);

  // /admin/entry?ballot=12 (from the ballot register; &edit=1 opens it for editing)
  const wanted = Number(params.get("ballot"));
  const wantedEdit = params.get("edit") === "1";
  const openWanted = useCallback(async () => {
    if (Number.isInteger(wanted) && wanted > 0) await open(wanted, wantedEdit);
  }, [wanted, wantedEdit, open]);
  useLoader(openWanted);

  const desk = state?.desks.find((d) => d.username === deskName) ?? state?.desks.find((d) => d.online) ?? state?.desks[0] ?? null;

  // the selected desk's last saved ballot, shown while nothing is being ticked there
  const lastKey = desk?.last_ballot_no ? `${desk.last_ballot_no}|${desk.last_saved_at}` : "";
  const lastNo = desk?.last_ballot_no ?? null;
  useEffect(() => {
    if (!token || !lastNo) return;
    let cancelled = false;
    api.entry.get(token, lastNo).then((ballot) => { if (!cancelled) setLastSaved(ballot); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [token, lastNo, lastKey]);

  // the list of saved ballots follows every save on any desk
  const savedKey = state ? state.desks.map((d) => `${d.entered}:${d.last_saved_at}:${d.pending_corrections}`).join("|") : "";
  useEffect(() => {
    if (!token || !savedKey) return;
    api.entry.recent(token, 15).then(setRecent).catch(() => undefined);
  }, [token, savedKey]);

  const find = (event: FormEvent) => {
    event.preventDefault();
    const number = Number(findNo);
    if (Number.isInteger(number) && number > 0) { void open(number); setFindNo(""); }
  };

  // editing applies to the opened ballot only: opening another one, a desk or a correction ends it
  const editing = edit !== null && opened !== null && reviewId === null && edit.ballotNo === opened.ballot_no ? edit : null;
  const toggleEdit = (id: number) => setEdit((current) => {
    if (!current) return current;
    const next = new Set(current.ids);
    if (next.has(id)) next.delete(id); else next.add(id);
    return { ...current, ids: next };
  });
  const selectAllEdit = (side: Side) => setEdit((current) => {
    if (!current) return current;
    const next = new Set(current.ids);
    const sideAll = sideIds(rows, side);
    const all = sideAll.every((id) => next.has(id));
    sideAll.forEach((id) => (all ? next.delete(id) : next.add(id)));
    return { ...current, ids: next };
  });
  const saveEdit = async () => {
    if (!token || !editing) return;
    setSavingEdit(true);
    try {
      const ballot = await api.entry.edit(token, editing.ballotNo, Array.from(editing.ids));
      toast.success(`Ballot ${ballot.label} changed: ${ballot.counted} vote${ballot.counted === 1 ? "" : "s"} counted now` +
        (ballot.null_marks ? `, ${ballot.null_marks} null mark${ballot.null_marks === 1 ? "" : "s"}` : "") + ". The dashboard is updated.");
      setOpened(ballot);
      setEdit(null);
      void loadCorrections();
      api.entry.recent(token, 15).then(setRecent).catch(() => undefined);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSavingEdit(false);
      setConfirmEdit(false);
    }
  };

  if (!state) return loadError ? <Alert type="error">{loadError}</Alert> : <Spinner label="Connecting to the entry desks…" />;
  if (!state.election) {
    return <EmptyState icon="landmark" title="No election is active"><p>Set the election to <strong>active</strong> under Elections; the Election Commissioners can then enter ballots.</p></EmptyState>;
  }

  // what the paper shows: a correction under review, else an opened ballot, else the desk's live ticks, else its last saved ballot
  const review = corrections.find((c) => c.id === reviewId) ?? null;
  const draft = desk?.draft ?? null;
  const saved = review ? null : opened ?? (!draft && lastSaved && desk && lastSaved.ballot_no === desk.last_ballot_no ? lastSaved : null);
  const mode: "review" | "opened" | "live" | "last" | "idle" = review ? "review" : opened ? "opened" : draft ? "live" : saved ? "last" : "idle";
  const ids = review ? (showSaved ? review.previous_candidate_ids : review.candidate_ids)
    : mode === "live" ? draft!.candidate_ids : saved?.candidate_ids ?? [];
  const selected = editing ? editing.ids : new Set(ids);
  const edited = editing !== null && opened !== null && !sameIds(editing.ids, opened.candidate_ids);
  const check = checkBallot(positions, candidates, selected);
  const label = review ? review.label : mode === "live" ? draft!.label : saved?.label ?? (desk?.next_label ?? "");
  const overall = state.total_ballots ? Math.round((state.total_entered / state.total_ballots) * 1000) / 10 : 0;

  return (
    <div className="page">
      <PageHeader eyebrow="Counting" title="Ballot entry · live monitor"
        subtitle="What EC1, EC2 and EC3 are entering right now. Ballots are entered at the desks; open any saved ballot to check it or to edit it."
        actions={<span className="badge badge-primary"><Icon name="vote" />{state.total_entered} of {state.total_ballots} entered · {overall}%</span>} />

      {loadError && <Alert type="error">Connection problem: {loadError}</Alert>}
      {layoutError && <Alert type="error">{layoutError}</Alert>}
      {state.election.counting_paused && <Alert type="warning"><strong>Counting is paused.</strong> The desks cannot save until START is pressed (Results &amp; Controls, or the live screen).</Alert>}

      {corrections.length > 0 && (
        <div className="card approval-card mb-6">
          <CardHead icon="shield" title={<>Corrections awaiting your approval <span className="badge badge-warning" style={{ marginLeft: 6 }}>{corrections.length}</span></>}
            subtitle="Sent by the entry desks. Nothing is counted from them until you approve; a rejected one leaves the ballot as it was saved." gold />
          <div className="approval-list">
            {corrections.map((c) => (
              <div key={c.id} className={`approval-row ${reviewId === c.id ? "is-active" : ""}`}>
                <span className="entry-recent-no">{c.label}</span>
                <div className="approval-info">
                  <strong>{c.requested_by}</strong> asks to correct ballot {c.label}
                  <small>{formatDateTime(c.requested_at)} · counted votes {c.previous_counted} → <b>{c.counted}</b> · null marks {c.previous_null_marks} → <b>{c.null_marks}</b> · boxes {c.previous_candidate_ids.length} → <b>{c.candidate_ids.length}</b></small>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => { setReviewId(c.id); setShowSaved(false); setOpened(null); }}><Icon name="eye" size={14} /> Compare</button>
                <button className="btn btn-success btn-sm" onClick={() => setDecision({ item: c, approve: true })}><Icon name="check" size={14} /> Approve</button>
                <button className="btn btn-danger-ghost btn-sm" onClick={() => setDecision({ item: c, approve: false })}><Icon name="x" size={14} /> Reject</button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="desk-grid">
        {state.desks.map((d) => {
          const complete = d.next_ballot_no === null;
          return (
            <button key={d.username} type="button" className={`desk-card ${desk?.username === d.username && !opened && !review ? "is-selected" : ""}`}
              onClick={() => { setDeskName(d.username); setOpened(null); setReviewId(null); }}>
              <div className="desk-head">
                <span className="avatar">{d.username}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="desk-name">{d.username}</div>
                  <div className="desk-sub">Ballots {rangeText(d, digits)}</div>
                </div>
                <span className={`desk-status ${complete ? "is-done" : d.online ? "is-online" : ""}`}><i />{complete ? "Complete" : d.online ? "Online" : "Offline"}</span>
              </div>
              <div className="desk-numbers"><strong>{d.entered}</strong><span>of {d.total} entered · {percent(d)}%</span></div>
              <div className="entry-progress"><span style={{ width: `${percent(d)}%` }} /></div>
              <div className="desk-foot">
                <span>{complete ? "Range finished" : d.draft
                  ? <>{d.draft.editing ? "Correcting" : "On the desk"}: <b>{d.draft.label}</b> · {d.draft.candidate_ids.length} ticked</>
                  : <>Next: <b>{d.next_label}</b></>}</span>
                <span>{d.pending_corrections > 0 ? <em className="entry-wait">{d.pending_corrections} correction{d.pending_corrections === 1 ? "" : "s"} to approve</em>
                  : d.last_label ? <>Last saved <b>{d.last_label}</b> {shortTime(d.last_saved_at)}</> : "Nothing saved yet"}</span>
              </div>
            </button>
          );
        })}
      </div>

      <div className="entry-layout">
        <div className="entry-paper-col">
          {review && (
            <div className="entry-banner is-edit">
              <Icon name="shield" size={20} />
              <div className="flex-1">Correction of ballot {review.label} by {review.requested_by} · {showSaved ? "as it is saved now" : "as it would be after approval"}
                <small>Counted votes {review.previous_counted} → {review.counted} · null marks {review.previous_null_marks} → {review.null_marks}. Compare both, then approve or reject.</small>
              </div>
              <div className="segmented" role="tablist">
                <button role="tab" aria-selected={showSaved} className={showSaved ? "active" : ""} onClick={() => setShowSaved(true)}>Saved</button>
                <button role="tab" aria-selected={!showSaved} className={!showSaved ? "active" : ""} onClick={() => setShowSaved(false)}>Corrected</button>
              </div>
              <button className="btn btn-success btn-sm" onClick={() => setDecision({ item: review, approve: true })}><Icon name="check" size={14} /> Approve</button>
              <button className="btn btn-danger-ghost btn-sm" onClick={() => setDecision({ item: review, approve: false })}><Icon name="x" size={14} /> Reject</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setReviewId(null)} aria-label="Close"><Icon name="x" size={14} /></button>
            </div>
          )}
          {editing && opened && (
            <div className="entry-banner is-edit">
              <Icon name="edit" size={20} />
              <div className="flex-1">Editing ballot {opened.label} · saved by {opened.entered_by ?? "—"}
                <small>Change the ticks, then save. No approval is needed: the totals, the dashboard and the reports change at once.{opened.pending ? ` ${opened.pending.requested_by} has a correction of this ballot waiting for approval.` : ""}</small>
              </div>
              <button className="btn btn-success btn-sm" onClick={() => setConfirmEdit(true)} disabled={!edited || savingEdit}><Icon name="save" size={14} /> Save changes</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setEdit(null)} disabled={savingEdit}><Icon name="undo" size={14} /> Cancel</button>
            </div>
          )}
          {mode === "opened" && saved && !editing && (
            <div className="entry-banner is-view">
              <Icon name="eye" size={20} />
              <div className="flex-1">Ballot {saved.label} · saved by {saved.entered_by ?? "—"}
                <small>{formatDateTime(saved.entered_at)}{saved.corrected_at ? ` · ${saved.approved_by ? `corrected by ${saved.corrected_by ?? "—"}, approved by ${saved.approved_by}` : `edited by ${saved.corrected_by ?? "—"}`} ${formatDateTime(saved.corrected_at)}` : ""}{saved.pending ? " · a correction is waiting for approval" : ""}</small>
              </div>
              <button className="btn btn-primary btn-sm" onClick={() => setEdit({ ballotNo: saved.ballot_no, ids: new Set(saved.candidate_ids) })} disabled={!ready}><Icon name="edit" size={14} /> Edit</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setOpened(null)}><Icon name="activity" size={14} /> Back to live</button>
            </div>
          )}
          {mode === "live" && desk && (
            <div className="entry-banner is-live">
              <span className="live-dot" style={{ width: 10, height: 10 }} />
              <div className="flex-1">{desk.username} is {draft!.editing ? "correcting" : "entering"} ballot {draft!.label}
                <small>Live: the ticks appear here as they are made. Nothing is counted until {desk.username} saves.</small>
              </div>
            </div>
          )}
          {mode === "last" && desk && saved && (
            <div className="entry-banner">
              <Icon name="checkCircle" size={20} />
              <div className="flex-1">{desk.username}: last saved ballot {saved.label}
                <small>{desk.online ? `Next on the desk: ${desk.next_label ?? "none, range complete"}` : `${desk.username} is not at the desk right now`}</small>
              </div>
            </div>
          )}
          {mode === "idle" && desk && (
            <div className="entry-banner">
              <Icon name="clock" size={20} />
              <div className="flex-1">{desk.username} has not entered a ballot yet
                <small>{desk.online ? `Ballot ${desk.next_label} is on the desk` : "Waiting for the commissioner to sign in"}</small>
              </div>
            </div>
          )}
          {!ready ? <Spinner label="Loading the ballot…" /> : (
            <BallotPaper
              titleBn={state.election.title_bn ?? FALLBACK_TITLE}
              ballotLabel={label}
              rows={rows} selected={selected} nullIds={check.nullIds} readOnly={!editing}
              onToggle={toggleEdit} onSelectAll={selectAllEdit}
              stamp={editing ? undefined : mode === "review" ? (showSaved ? "Saved" : "Proposed") : mode === "opened" || mode === "last" ? (saved?.status === "reviewed" ? "Corrected" : "Saved") : undefined}
              flashKey={`${mode}-${label}-${showSaved}-${editing ? "edit" : "view"}`}
            />
          )}
        </div>

        <aside className="entry-side">
          <div className="card card-gold">
            <CardHead icon="vote" title={mode === "live" ? `Ballot ${label} · live` : label ? `Ballot ${label}` : "Ballot"}
              subtitle={mode === "review" ? (showSaved ? "As saved now" : "As it would be after approval") : editing ? (edited ? "As it would be after saving" : "As saved: change the ticks on the paper") : mode === "live" ? "Not saved yet" : mode === "idle" ? "Nothing to show yet" : "As saved"} gold />
            <TallyCard check={check} />
          </div>

          <div className="card">
            <CardHead icon="search" title="Open a ballot" subtitle="Any saved ballot, by its number" />
            <form className="entry-find" onSubmit={find}>
              <input className="input" inputMode="numeric" placeholder="Ballot no., e.g. 12" value={findNo} onChange={(e) => setFindNo(e.target.value.replace(/\D/g, ""))} aria-label="Ballot number to open" />
              <button className="btn btn-primary" type="submit" disabled={!findNo}><Icon name="eye" size={15} /> View</button>
            </form>
          </div>

          <div className="card">
            <CardHead icon="scroll" title="Latest saved ballots" subtitle="All desks, newest number first" />
            <RecentList ballots={recent} activeNo={opened?.ballot_no ?? null} onPick={(b) => { setReviewId(null); setOpened(b); window.scrollTo({ top: 0, behavior: "smooth" }); }} empty="No ballot saved yet." showDesk />
          </div>
        </aside>
      </div>

      <ConfirmDialog open={confirmEdit && editing !== null} busy={savingEdit}
        title={`Save the changes to ballot ${opened?.label ?? ""}`}
        message={opened
          ? `Ballot ${opened.label} (entered by ${opened.entered_by ?? "—"}) will be changed: boxes marked ${opened.candidate_ids.length} → ${check.marked}, counted votes ${opened.counted} → ${check.counted}, null marks ${opened.null_marks} → ${check.nullIds.size}.`
            + (check.marked === 0 ? " No box is ticked: it becomes a blank ballot." : "")
            + " The totals, the dashboard and the reports change at once, and the change is written to the audit log."
          : ""}
        confirmLabel="Save changes" onConfirm={saveEdit} onCancel={() => setConfirmEdit(false)} />

      <ConfirmDialog open={decision !== null} busy={deciding} danger={decision ? !decision.approve : false}
        title={decision ? `${decision.approve ? "Approve" : "Reject"} the correction of ballot ${decision.item.label}` : ""}
        message={decision
          ? decision.approve
            ? `Ballot ${decision.item.label} will be changed as ${decision.item.requested_by} asked: counted votes ${decision.item.previous_counted} → ${decision.item.counted}, null marks ${decision.item.previous_null_marks} → ${decision.item.null_marks}. The totals, the dashboard and the reports change at once.`
            : `The correction ${decision.item.requested_by} sent for ballot ${decision.item.label} is refused. The ballot and the totals stay exactly as they are.`
          : ""}
        confirmLabel={decision?.approve ? "Approve" : "Reject"} onConfirm={decide} onCancel={() => setDecision(null)} />
    </div>
  );
}
