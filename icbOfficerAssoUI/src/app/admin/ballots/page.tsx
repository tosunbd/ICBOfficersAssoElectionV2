"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage, formatDateTime } from "@/lib/format";
import type { Ballot } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import { useElection } from "@/hooks/useElection";
import { useLoader } from "@/hooks/useLoader";
import { useToast } from "@/components/ui/Toast";
import { BallotStatusBadge, CardHead, EmptyState, PageHeader } from "@/components/ui/Basics";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/Modal";

type Filter = "" | "EC1" | "EC2" | "EC3" | "null" | "reviewed";
const FILTERS: Array<{ value: Filter; label: string; color?: string }> = [
  { value: "", label: "All" },
  { value: "EC1", label: "EC1" },
  { value: "EC2", label: "EC2" },
  { value: "EC3", label: "EC3" },
  { value: "null", label: "With null votes", color: "var(--color-error)" },
  { value: "reviewed", label: "Corrected", color: "var(--color-primary-300)" },
];
const PER_PAGE = 25;

/** The register of entered ballots.  SA and Admin can edit any of them; deleting is for the Super Admin. */
export default function BallotsPage() {
  const { token, isSuperAdmin } = useAuth();
  const { election } = useElection();
  const toast = useToast();
  const [ballots, setBallots] = useState<Ballot[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<Filter>("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async () => {
    if (!token || !election) return;
    try {
      const data = await api.ballots.list(token, election.id, page, PER_PAGE, {
        enteredBy: filter.startsWith("EC") ? filter : undefined,
        nullOnly: filter === "null",
        status: filter === "reviewed" ? "reviewed" : undefined,
        ballotNo: Number(search) || undefined,
      });
      setBallots(data.ballots);
      setTotal(data.total);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }, [token, election, page, filter, search, toast]);

  useLoader(load, 4000);  // the register follows the entry desks

  const clearSelection = () => setSelected(new Set());
  const toggleOne = (id: number) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const pageIds = ballots.map((b) => b.id);
  const pageAllSelected = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const pageSomeSelected = pageIds.some((id) => selected.has(id));
  const togglePage = () => setSelected((current) => {
    const next = new Set(current);
    if (pageAllSelected) pageIds.forEach((id) => next.delete(id)); else pageIds.forEach((id) => next.add(id));
    return next;
  });

  const deleteSelected = async () => {
    if (!token || !election) return;
    setBusy(true);
    try {
      const result = await api.ballots.bulkRemove(token, { ballot_ids: Array.from(selected) });
      toast.success(`${result.deleted} ballot${result.deleted === 1 ? "" : "s"} deleted; ${result.deleted === 1 ? "its desk enters it" : "their desks enter them"} again`);
      clearSelection();
      await load();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
      setConfirmDelete(false);
    }
  };

  if (!election) return <EmptyState icon="landmark" title="Create an election first" />;
  const pages = Math.max(1, Math.ceil(total / PER_PAGE));
  const first = total === 0 ? 0 : (page - 1) * PER_PAGE + 1;

  return (
    <div className="page">
      <PageHeader eyebrow="Counting" title="Ballots" subtitle="Every ballot saved by EC1, EC2 and EC3. Open one to see it exactly as it was entered, or edit it."
        actions={<Link href="/admin/entry" className="btn btn-accent"><Icon name="activity" size={16} /> Live entry monitor</Link>} />

      <div className="card">
        <CardHead icon="ballot" title={<>Ballot register <span className="badge badge-muted" style={{ marginLeft: 6 }}>{total}</span></>} gold>
          <div className="input-wrap" style={{ width: 170 }}>
            <Icon name="search" size={15} />
            <input className="input input-sm" inputMode="numeric" placeholder="Ballot no." value={search} aria-label="Find a ballot by its number"
              onChange={(e) => { setSearch(e.target.value.replace(/\D/g, "")); setPage(1); }} />
          </div>
          <div className="segmented" role="tablist">
            {FILTERS.map((f) => (
              <button key={f.value} role="tab" aria-selected={filter === f.value} className={filter === f.value ? "active" : ""}
                onClick={() => { setFilter(f.value); setPage(1); clearSelection(); }}>
                {f.color && <span className="seg-dot" style={{ color: f.color }} />}{f.label}
              </button>
            ))}
          </div>
        </CardHead>

        {ballots.length === 0 ? (
          <div className="empty-inline"><Icon name="inbox" size={32} />No ballots{filter || search ? " match" : " entered yet"}.</div>
        ) : (
          <div className="table-wrapper">
            <table className="table">
              <thead>
                <tr>
                  {isSuperAdmin && (
                    <th className="cell-check">
                      <input type="checkbox" className="check" aria-label="Select all ballots on this page" checked={pageAllSelected}
                        ref={(el) => { if (el) el.indeterminate = !pageAllSelected && pageSomeSelected; }} onChange={togglePage} />
                    </th>
                  )}
                  <th>Ballot no.</th><th>Entered by</th><th>Status</th><th className="num">Marked</th><th className="num">Counted</th><th className="num">Null</th><th>Saved</th><th></th>
                </tr>
              </thead>
              <tbody>
                {ballots.map((b) => {
                  const nulls = b.boxes_detected - b.total_votes_extracted;
                  return (
                    <tr key={b.id} className={`${nulls > 0 ? "row-attention" : ""} ${selected.has(b.id) ? "row-selected" : ""}`}>
                      {isSuperAdmin && (
                        <td className="cell-check">
                          <input type="checkbox" className="check" aria-label={`Select ballot ${b.ballot_paper_no}`} checked={selected.has(b.id)} onChange={() => toggleOne(b.id)} />
                        </td>
                      )}
                      <td><Link href={`/admin/entry?ballot=${b.ballot_no ?? ""}`} className="row-link"><span className="chip-no">{b.ballot_paper_no ?? `#${b.id}`}</span></Link></td>
                      <td><span className="badge badge-muted">{b.entered_by ?? "—"}</span>{b.corrected_by && <span className="text-faint text-small"> · corrected by {b.corrected_by}{b.approved_by ? `, approved by ${b.approved_by}` : ""}</span>}</td>
                      <td>
                        <span className="flex items-center gap-2">
                          <BallotStatusBadge status={b.status} />
                          {b.ocr_warnings.length > 0 && <span title={b.ocr_warnings.join("\n")} className="text-warning" style={{ display: "inline-flex" }}><Icon name="alert" size={15} /></span>}
                        </span>
                      </td>
                      <td className="num">{b.boxes_detected === 0 ? <span className="badge badge-muted">blank</span> : b.boxes_detected}</td>
                      <td className="num"><strong>{b.total_votes_extracted}</strong></td>
                      <td className="num">{nulls > 0 ? <strong className="text-error">{nulls}</strong> : <span className="text-faint">0</span>}</td>
                      <td className="text-faint text-small" style={{ whiteSpace: "nowrap" }}>{formatDateTime(b.reviewed_at ?? b.processed_at ?? b.scanned_at)}</td>
                      <td className="cell-actions">
                        <Link href={`/admin/entry?ballot=${b.ballot_no ?? ""}`} className="btn btn-sm btn-ghost">View <Icon name="chevronRight" size={14} /></Link>
                        <Link href={`/admin/entry?ballot=${b.ballot_no ?? ""}&edit=1`} className="btn btn-sm btn-ghost"><Icon name="edit" size={14} /> Edit</Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {pages > 1 && (
          <div className="pager">
            <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}><Icon name="arrowLeft" size={14} /> Previous</button>
            <span className="pager-info">{first}–{Math.min(total, page * PER_PAGE)} of {total} · page {page} of {pages}</span>
            <button className="btn btn-ghost btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next <Icon name="arrowRight" size={14} /></button>
          </div>
        )}
      </div>

      {isSuperAdmin && selected.size > 0 && (
        <div className="action-bar" role="region" aria-label="Selected ballots">
          <span className="action-bar-count"><span className="action-bar-num">{selected.size}</span> ballot{selected.size === 1 ? "" : "s"} selected</span>
          <button className="btn btn-ghost btn-sm" onClick={clearSelection}><Icon name="x" size={14} /> Clear</button>
          <button className="btn btn-danger btn-sm" onClick={() => setConfirmDelete(true)} disabled={busy}><Icon name="trash" size={14} /> Delete selected</button>
        </div>
      )}

      <ConfirmDialog open={confirmDelete} danger busy={busy}
        title={`Delete ${selected.size} ballot${selected.size === 1 ? "" : "s"}`}
        message={`Delete ${selected.size === 1 ? "this ballot" : `these ${selected.size} ballots`} and the votes on ${selected.size === 1 ? "it" : "them"}? The totals go down accordingly, and each deleted number becomes the next ballot its desk has to enter again.`}
        confirmLabel="Delete" onConfirm={deleteSelected} onCancel={() => setConfirmDelete(false)} />
    </div>
  );
}
