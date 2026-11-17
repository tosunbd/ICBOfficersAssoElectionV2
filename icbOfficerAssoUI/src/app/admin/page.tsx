"use client";

import "../entry.css";
import Link from "next/link";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import type { Ballot, DashboardData, EntryState } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import { useElection } from "@/hooks/useElection";
import { useLoader } from "@/hooks/useLoader";
import { useToast } from "@/components/ui/Toast";
import { Alert, CardHead, ElectionStatusBadge, EmptyState, Skeleton, Spinner } from "@/components/ui/Basics";
import { StatsGrid } from "@/components/dashboard/ResultsView";
import { Icon } from "@/components/ui/Icon";
import { AnimatedNumber, RingGauge } from "@/components/ui/Motion";

/** The summary is read again from the database this often. */
const REFRESH_MS = 2000;

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

export default function OverviewPage() {
  const { token, username } = useAuth();
  const { election, elections, loading, patch } = useElection();
  const toast = useToast();
  const [data, setData] = useState<DashboardData | null>(null);
  const [entry, setEntry] = useState<EntryState | null>(null);
  const [recent, setRecent] = useState<Ballot[]>([]);

  const load = useCallback(async () => {
    if (!token || !election) return;
    try {
      const [results, state, ballots] = await Promise.all([
        api.dashboard.results(election.id, token),
        api.entry.state(token),
        api.ballots.list(token, election.id, 1, 8),
      ]);
      setData(results);
      setEntry(state);
      setRecent(ballots.ballots);
    } catch (err) {
      console.error(errorMessage(err));  // the next refresh tries again
    }
  }, [token, election]);

  useLoader(load, REFRESH_MS);

  const togglePublish = async () => {
    if (!token || !election) return;
    try {
      await api.admin.publish(token, election.id, !election.dashboard_published);
      patch({ dashboard_published: !election.dashboard_published });
      toast.success(election.dashboard_published ? "Results hidden from the public dashboard" : "Results published to the public dashboard");
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const togglePause = async () => {
    if (!token || !election) return;
    try {
      await api.admin.pause(token, election.id, !election.dashboard_paused);
      patch({ dashboard_paused: !election.dashboard_paused });
      toast.success(`Live updates ${election.dashboard_paused ? "resumed" : "paused"}`);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  if (loading) return <Spinner label="Loading…" />;

  if (elections.length === 0 || !election) {
    return (
      <div className="page">
        <div className="page-header"><div><div className="page-eyebrow">Welcome</div><h1>Let&apos;s set up the election</h1><p>Three quick steps and the counting room is ready.</p></div></div>
        <EmptyState icon="landmark" title="No election yet">
          <p>Create one under <Link href="/admin/elections">Elections</Link>, seed the positions, add the candidates, then set it to <strong>active</strong>.</p>
          <Link href="/admin/elections" className="btn btn-accent mt-6"><Icon name="plus" size={16} /> Create the election</Link>
        </EmptyState>
      </div>
    );
  }

  const stats = data?.stats;
  const desks = entry?.election?.id === election.id ? entry.desks : [];

  return (
    <div className="page">
      <section className="hero">
        <div>
          <div className="hero-greeting"><Icon name="sparkles" size={15} style={{ color: "var(--color-accent-text)" }} />{greeting()}, {username}</div>
          {election.title_bn ? (
            <>
              <h1 className="hero-title hero-title-main-bn">{election.title_bn}</h1>
              <div className="hero-title-en">{election.title}</div>
            </>
          ) : <h1 className="hero-title">{election.title}</h1>}
          <div className="hero-pills">
            <ElectionStatusBadge status={election.status} />
            <span className="badge badge-muted"><Icon name="landmark" />{election.year}</span>
            <span className="badge badge-muted"><Icon name="users" />{election.total_voters.toLocaleString()} voters</span>
            <span className={`badge ${election.dashboard_published ? "badge-success" : "badge-muted"}`}><Icon name={election.dashboard_published ? "eye" : "eyeOff"} />{election.dashboard_published ? "Results public" : "Results hidden"}</span>
            <span className="badge badge-primary"><Icon name="refresh" />Updated every 2 seconds</span>
          </div>
          <div className="hero-actions">
            <Link href="/admin/entry" className="btn btn-primary"><Icon name="activity" size={17} /> Watch the entry desks</Link>
            <Link href="/admin/reports" className="btn btn-accent"><Icon name="scroll" size={16} /> Reports</Link>
            <button className={`btn ${election.dashboard_published ? "btn-danger-ghost" : "btn-ghost"}`} onClick={togglePublish}>
              <Icon name={election.dashboard_published ? "lock" : "broadcast"} size={16} />
              {election.dashboard_published ? "Hide results" : "Publish results"}
            </button>
            <button className="btn btn-ghost" onClick={togglePause}>
              <Icon name={election.dashboard_paused ? "play" : "pause"} size={15} />
              {election.dashboard_paused ? "Resume live updates" : "Pause live updates"}
            </button>
          </div>
        </div>
        <RingGauge value={stats?.turnout_percentage ?? 0} size={196} stroke={14}>
          <div className="hero-gauge-value"><AnimatedNumber value={stats?.turnout_percentage ?? 0} suffix="%" /></div>
          <div className="hero-gauge-label">Entered</div>
          <div className="hero-gauge-sub">{stats ? `${stats.counted_ballots} of ${stats.total_voters}` : "—"}</div>
        </RingGauge>
      </section>

      {election.status !== "active" && (
        <Alert type="warning">
          This election is <strong>{election.status}</strong>. Ballots can only be entered into the <strong>active</strong> election.
          Change the status under <Link href="/admin/elections">Elections</Link>.
        </Alert>
      )}
      {election.counting_paused && <Alert type="warning"><strong>Counting is paused.</strong> The entry desks cannot save until START is pressed on the dashboard.</Alert>}

      <div className="mb-6">
        {stats ? <StatsGrid stats={stats} /> : (
          <div className="stats-grid">{[0, 1, 2, 3].map((i) => <Skeleton key={i} height={128} style={{ borderRadius: 18 }} />)}</div>
        )}
      </div>

      {desks.length > 0 && (
        <div className="desk-grid">
          {desks.map((d) => {
            const complete = d.next_ballot_no === null;
            const pct = d.total ? Math.round((d.entered / d.total) * 1000) / 10 : 0;
            return (
              <Link key={d.username} href="/admin/entry" className="desk-card" style={{ textDecoration: "none" }}>
                <div className="desk-head">
                  <span className="avatar">{d.username}</span>
                  <div style={{ minWidth: 0 }}>
                    <div className="desk-name">{d.username}</div>
                    <div className="desk-sub">{d.full_name}</div>
                  </div>
                  <span className={`desk-status ${complete ? "is-done" : d.online ? "is-online" : ""}`}><i />{complete ? "Complete" : d.online ? "Online" : "Offline"}</span>
                </div>
                <div className="desk-numbers"><strong><AnimatedNumber value={d.entered} /></strong><span>of {d.total} entered · {pct}%</span></div>
                <div className="entry-progress"><span style={{ width: `${pct}%` }} /></div>
                <div className="desk-foot">
                  <span>{complete ? "Range finished" : d.draft ? <>On the desk: <b>{d.draft.label}</b></> : <>Next: <b>{d.next_label}</b></>}</span>
                  <span>{d.last_label ? <>Last saved <b>{d.last_label}</b></> : "Nothing saved yet"}</span>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <div className="card">
        <CardHead icon="activity" title="Latest ballots" subtitle="Refreshes every 2 seconds" gold>
          <Link href="/admin/ballots" className="btn btn-ghost btn-sm">View all <Icon name="arrowRight" size={14} /></Link>
        </CardHead>
        {recent.length === 0 ? (
          <div className="empty-inline"><Icon name="inbox" size={30} />No ballot entered yet.<br />Ballots saved by EC1, EC2 and EC3 appear here.</div>
        ) : (
          <ul className="timeline stagger">
            {recent.map((b) => {
              const nulls = b.boxes_detected - b.total_votes_extracted;
              return (
                <li key={b.id}>
                  <Link href={`/admin/entry?ballot=${b.ballot_no ?? ""}`} className="timeline-item" style={{ color: "inherit" }}>
                    <span className={`timeline-dot ${nulls > 0 ? "warning" : b.status === "reviewed" ? "accent" : "success"}`}>
                      <Icon name={nulls > 0 ? "alert" : b.status === "reviewed" ? "edit" : "check"} size={16} strokeWidth={2.2} />
                    </span>
                    <div className="timeline-body">
                      <div className="timeline-title">
                        Ballot <span className="chip-no">{b.ballot_paper_no ?? b.id}</span>
                        <span className="text-faint text-xs" style={{ fontWeight: 600 }}>{b.status === "reviewed" ? "Corrected" : "Entered"} by {b.corrected_by ?? b.entered_by ?? "—"}</span>
                      </div>
                      <div className="timeline-meta">{formatDateTime(b.reviewed_at ?? b.processed_at ?? b.scanned_at)}{nulls > 0 ? ` · ${nulls} null mark${nulls === 1 ? "" : "s"}` : ""}</div>
                    </div>
                    <div className="timeline-right"><strong>{b.total_votes_extracted}</strong>votes</div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
