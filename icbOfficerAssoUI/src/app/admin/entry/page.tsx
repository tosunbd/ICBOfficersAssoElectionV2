"use client";

import "../../entry.css";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import type { Candidate, Desk, EntryBallot, EntryState, Position } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import { useLoader } from "@/hooks/useLoader";
import { useToast } from "@/components/ui/Toast";
import { Modal } from "@/components/ui/Modal";
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

  useLoader(loadState, 4000);
  useLoader(loadRecent);

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
      toast.success(
        `Ballot ${b.label} ${editing ? "corrected" : "saved"}: ${b.counted} vote${b.counted === 1 ? "" : "s"} counted` +
        (b.null_marks ? `, ${b.null_marks} null mark${b.null_marks === 1 ? "" : "s"}` : ""),
      );
      setSelected(new Set());
      setEditing(null);
      try { sessionStorage.removeItem(draftKey(username)); } catch { /* ignore */ }
      setState((old) => (old ? { ...old, desks: old.desks.map((d) => (d.username === result.desk.username ? result.desk : d)) } : old));
      window.scrollTo({ top: 0, behavior: "smooth" });
      void loadRecent();
      void loadState();
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
    setSelected(new Set(ballot.candidate_ids));
    window.scrollTo({ top: 0, behavior: "smooth" });
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
  const edited = editing !== null && Array.from(selected).sort((a, b) => a - b).join(",") !== [...editing.candidate_ids].sort((a, b) => a - b).join(",");

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
              <div className="flex-1">Correcting ballot {editing.label}
                <small>Saved {formatDateTime(editing.corrected_at ?? editing.entered_at)}. Change the ticks and save the correction, or go back.</small>
              </div>
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
                    : editing ? <><Icon name="save" size={18} /> Save correction</>
                    : <><Icon name="save" size={18} /> Save &amp; next ballot</>}
                </button>
                <button className="btn btn-ghost" onClick={() => setSelected(new Set(editing ? editing.candidate_ids : []))} disabled={busy || (editing ? !edited : selected.size === 0)}>
                  <Icon name="undo" size={15} /> {editing ? "Reset to the saved ticks" : "Clear the form"}
                </button>
              </div>
              <p className="entry-hint">
                <kbd>Ctrl</kbd> + <kbd>Enter</kbd> saves. Several boxes of one post may be ticked, as on the paper: a post with more marks than allowed
                (1, or 3 for <span className="text-bengali">নির্বাহী সদস্য</span>) becomes a null vote.
              </p>
            </div>
          )}

          <div className="card">
            <CardHead icon="scroll" title="Your saved ballots" subtitle="Click one to check or correct it" />
            <RecentList ballots={recent} activeNo={editing?.ballot_no ?? null} onPick={startEdit} empty="Nothing saved yet." />
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

      <Modal open={confirm !== null} title={confirm === "blank" ? `Save ballot ${currentLabel} as blank?` : `Ballot ${currentLabel} has null votes`} onClose={() => setConfirm(null)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setConfirm(null)} disabled={busy}>Go back and check</button>
            <button className="btn btn-primary" onClick={() => void save()} disabled={busy} autoFocus>
              <Icon name="save" size={16} /> Yes, save it <span className="entry-kbd" style={{ marginLeft: 6 }}>Enter</span>
            </button>
          </>
        }>
        {confirm === "blank" ? (
          <div className="confirm-body">
            <span className="confirm-icon"><Icon name="info" size={22} /></span>
            <p style={{ paddingTop: 10 }}>No box is ticked. The ballot will be saved with <strong>no votes</strong>. Save it only if the paper really is blank.</p>
          </div>
        ) : (
          <div>
            <p className="text-muted" style={{ marginBottom: 12 }}>These posts have more marks than allowed, so <strong>no vote is counted for them</strong>. The other posts count as usual. Save if the paper really is marked this way.</p>
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
/*  Super Admin / Admin: watch the three desks (read only)             */
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

  const digits = state?.digits ?? 3;
  const { positions, candidates, rows, ready, error: layoutError } = useBallotLayout(state?.election?.id ?? null);

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

  const open = useCallback(async (ballotNo: number) => {
    if (!token) return;
    try {
      setOpened(await api.entry.get(token, ballotNo));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }, [token, toast]);

  // /admin/entry?ballot=12 (from the ballot register)
  const wanted = Number(params.get("ballot"));
  const openWanted = useCallback(async () => {
    if (Number.isInteger(wanted) && wanted > 0) await open(wanted);
  }, [wanted, open]);
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
  const savedKey = state ? state.desks.map((d) => `${d.entered}:${d.last_saved_at}`).join("|") : "";
  useEffect(() => {
    if (!token || !savedKey) return;
    api.entry.recent(token, 15).then(setRecent).catch(() => undefined);
  }, [token, savedKey]);

  const find = (event: FormEvent) => {
    event.preventDefault();
    const number = Number(findNo);
    if (Number.isInteger(number) && number > 0) { void open(number); setFindNo(""); }
  };

  if (!state) return loadError ? <Alert type="error">{loadError}</Alert> : <Spinner label="Connecting to the entry desks…" />;
  if (!state.election) {
    return <EmptyState icon="landmark" title="No election is active"><p>Set the election to <strong>active</strong> under Elections; the Election Commissioners can then enter ballots.</p></EmptyState>;
  }

  // what the paper shows: an opened ballot, else the desk's live ticks, else its last saved ballot
  const draft = desk?.draft ?? null;
  const saved = opened ?? (!draft && lastSaved && desk && lastSaved.ballot_no === desk.last_ballot_no ? lastSaved : null);
  const mode: "opened" | "live" | "last" | "idle" = opened ? "opened" : draft ? "live" : saved ? "last" : "idle";
  const ids = mode === "live" ? draft!.candidate_ids : saved?.candidate_ids ?? [];
  const selected = new Set(ids);
  const check = checkBallot(positions, candidates, selected);
  const label = mode === "live" ? draft!.label : saved?.label ?? (desk?.next_label ?? "");
  const overall = state.total_ballots ? Math.round((state.total_entered / state.total_ballots) * 1000) / 10 : 0;

  return (
    <div className="page">
      <PageHeader eyebrow="Counting" title="Ballot entry · live monitor"
        subtitle="What EC1, EC2 and EC3 are entering right now. View only: ballots are entered and corrected at the desks."
        actions={<span className="badge badge-primary"><Icon name="vote" />{state.total_entered} of {state.total_ballots} entered · {overall}%</span>} />

      {loadError && <Alert type="error">Connection problem: {loadError}</Alert>}
      {layoutError && <Alert type="error">{layoutError}</Alert>}
      {state.election.counting_paused && <Alert type="warning"><strong>Counting is paused.</strong> The desks cannot save until START is pressed (Results &amp; Controls, or the live screen).</Alert>}

      <div className="desk-grid">
        {state.desks.map((d) => {
          const complete = d.next_ballot_no === null;
          return (
            <button key={d.username} type="button" className={`desk-card ${desk?.username === d.username && !opened ? "is-selected" : ""}`}
              onClick={() => { setDeskName(d.username); setOpened(null); }}>
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
                <span>{d.last_label ? <>Last saved <b>{d.last_label}</b> {shortTime(d.last_saved_at)}</> : "Nothing saved yet"}</span>
              </div>
            </button>
          );
        })}
      </div>

      <div className="entry-layout">
        <div className="entry-paper-col">
          {mode === "opened" && saved && (
            <div className="entry-banner is-view">
              <Icon name="eye" size={20} />
              <div className="flex-1">Ballot {saved.label} · saved by {saved.entered_by ?? "—"}
                <small>{formatDateTime(saved.entered_at)}{saved.corrected_at ? ` · corrected by ${saved.corrected_by ?? "—"} ${formatDateTime(saved.corrected_at)}` : ""}</small>
              </div>
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
              rows={rows} selected={selected} nullIds={check.nullIds} readOnly
              stamp={mode === "opened" || mode === "last" ? (saved?.status === "reviewed" ? "Corrected" : "Saved") : undefined}
              flashKey={`${mode}-${label}`}
            />
          )}
        </div>

        <aside className="entry-side">
          <div className="card card-gold">
            <CardHead icon="vote" title={mode === "live" ? `Ballot ${label} · live` : label ? `Ballot ${label}` : "Ballot"} subtitle={mode === "live" ? "Not saved yet" : mode === "idle" ? "Nothing to show yet" : "As saved"} gold />
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
            <RecentList ballots={recent} activeNo={opened?.ballot_no ?? null} onPick={(b) => { setOpened(b); window.scrollTo({ top: 0, behavior: "smooth" }); }} empty="No ballot saved yet." showDesk />
          </div>
        </aside>
      </div>
    </div>
  );
}
