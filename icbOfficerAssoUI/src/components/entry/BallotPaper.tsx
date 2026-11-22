"use client";

import { useMemo } from "react";
import type { Candidate, Position } from "@/lib/types";
import { toBengaliDigits } from "@/lib/format";
import { withBase } from "@/lib/basePath";

/**
 * The ballot paper as an entry form: the same layout as the printed paper
 * (Blank_ballot_form.docx of 22-11-2026) — QR code, title and the large paper
 * number box on top, then one row per pair of candidates with the post name in
 * the middle and a box beside every name, the instructions underneath and the
 * bar code at the bottom centre.  QR code and bar code are the pictures of the
 * printed paper (the same on every ballot: "ICBOA-20-2026").
 *
 * Added for entry: a "Select all" tick at the right of each
 * "ভোটার নং ও প্রার্থীর নাম" heading, above the boxes of that side.
 *
 * Any number of boxes can be ticked, exactly as a voter may have marked the
 * paper; boxes of a post with more marks than it allows are drawn in red
 * (null vote, not counted).
 */

export type Side = "left" | "right";

export interface BallotRow {
  position: Position;
  /** rows this post spans (set on its first row only, 0 on the others) */
  span: number;
  left: Candidate | null;
  right: Candidate | null;
}

/** Candidates in ballot order -> rows of the paper (left box, right box, next row ...). */
export function buildRows(positions: Position[], candidates: Candidate[]): BallotRow[] {
  const rows: BallotRow[] = [];
  [...positions].sort((a, b) => a.position_order - b.position_order).forEach((position) => {
    const list = candidates
      .filter((c) => c.position_id === position.id)
      .sort((a, b) => a.display_order - b.display_order || a.id - b.id);
    const count = Math.max(1, Math.ceil(list.length / 2));
    for (let i = 0; i < count; i++) {
      rows.push({ position, span: i === 0 ? count : 0, left: list[i * 2] ?? null, right: list[i * 2 + 1] ?? null });
    }
  });
  return rows;
}

export function sideIds(rows: BallotRow[], side: Side): number[] {
  return rows.map((row) => row[side]?.id).filter((id): id is number => id !== undefined);
}

export interface PostCheck {
  position: Position;
  marked: number;
  /** more marks than the post allows: none of them counts */
  isNull: boolean;
}

/** What the rules make of the ticked boxes: per post, and the ids that do not count. */
export function checkBallot(positions: Position[], candidates: Candidate[], selected: ReadonlySet<number>) {
  const posts: PostCheck[] = [];
  const nullIds = new Set<number>();
  let counted = 0;
  [...positions].sort((a, b) => a.position_order - b.position_order).forEach((position) => {
    const marked = candidates.filter((c) => c.position_id === position.id && selected.has(c.id));
    const isNull = marked.length > position.max_selections;
    if (isNull) marked.forEach((c) => nullIds.add(c.id));
    else counted += marked.length;
    posts.push({ position, marked: marked.length, isNull });
  });
  return { posts, nullIds, counted, marked: selected.size, nullPosts: posts.filter((p) => p.isNull), blankPosts: posts.filter((p) => p.marked === 0) };
}

function MarkBox({ on, isNull }: { on: boolean; isNull: boolean }) {
  return (
    <span className={`bp-box ${on ? "is-on" : ""} ${isNull ? "is-null" : ""}`} aria-hidden="true">
      {on && (
        <svg viewBox="0 0 120 78" preserveAspectRatio="none">
          <line x1="10" y1="9" x2="110" y2="69" />
          <line x1="110" y1="9" x2="10" y2="69" />
        </svg>
      )}
    </span>
  );
}

function CandidateCells({ candidate, on, isNull, readOnly, onToggle }: {
  candidate: Candidate | null; on: boolean; isNull: boolean; readOnly?: boolean; onToggle?: (id: number) => void;
}) {
  if (!candidate) return <><td className="bp-name" /><td className="bp-boxcell" /></>;
  const name = candidate.name_bn ?? candidate.name_en;
  const toggle = () => { if (!readOnly) onToggle?.(candidate.id); };
  return (
    <>
      <td className={`bp-name ${on ? "is-on" : ""} ${isNull ? "is-null" : ""} ${readOnly ? "" : "is-clickable"}`} onClick={toggle}>
        <span className="bp-voter">{toBengaliDigits(candidate.voter_no)}</span>
        <span className="bp-cname">{name}</span>
      </td>
      <td className={`bp-boxcell ${on ? "is-on" : ""} ${isNull ? "is-null" : ""}`}>
        <button
          type="button" className="bp-boxbtn" onClick={toggle} disabled={readOnly}
          role="checkbox" aria-checked={on}
          aria-label={`${candidate.voter_no} ${candidate.name_en}${isNull ? " (null vote)" : ""}`}
          title={isNull ? "Null vote: more marks than this post allows" : undefined}
        >
          <MarkBox on={on} isNull={isNull} />
        </button>
      </td>
    </>
  );
}

function HeadCell({ side, state, readOnly, onSelectAll }: {
  side: Side; state: "all" | "some" | "none"; readOnly?: boolean; onSelectAll?: (side: Side) => void;
}) {
  return (
    <th colSpan={2} className="bp-head">
      <div className="bp-head-inner">
        <span className="bp-head-title">ভোটার নং ও<br />প্রার্থীর নাম</span>
        <label className={`bp-selectall ${state !== "none" ? "is-on" : ""} ${readOnly ? "is-readonly" : ""}`} title={`Tick / clear every box on the ${side} side`}>
          <input
            type="checkbox" checked={state === "all"} disabled={readOnly}
            ref={(el) => { if (el) el.indeterminate = state === "some"; }}
            onChange={() => onSelectAll?.(side)}
            aria-label={`Select all candidates on the ${side} side`}
          />
          <span>Select all</span>
        </label>
      </div>
    </th>
  );
}

export function BallotPaper({ titleBn, ballotLabel, rows, selected, nullIds, readOnly, onToggle, onSelectAll, stamp, flashKey }: {
  titleBn: string;
  /** "001"; empty = no paper on the desk */
  ballotLabel: string;
  rows: BallotRow[];
  selected: ReadonlySet<number>;
  nullIds: ReadonlySet<number>;
  readOnly?: boolean;
  onToggle?: (candidateId: number) => void;
  onSelectAll?: (side: Side) => void;
  /** small note printed diagonally over the paper, e.g. "SAVED" on a ballot being viewed */
  stamp?: string;
  /** change it to play the "next paper" animation */
  flashKey?: string | number;
}) {
  const sideState = useMemo(() => {
    const of = (side: Side): "all" | "some" | "none" => {
      const ids = sideIds(rows, side);
      const on = ids.filter((id) => selected.has(id)).length;
      return on === 0 ? "none" : on === ids.length ? "all" : "some";
    };
    return { left: of("left"), right: of("right") };
  }, [rows, selected]);

  return (
    <div className={`bp ${readOnly ? "is-readonly" : ""}`} key={flashKey}>
      {stamp && <div className="bp-stamp" aria-hidden="true">{stamp}</div>}
      <div className="bp-top">
        <div className="bp-heading">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="bp-qr" src={withBase("/ballot-qr.png")} alt="QR code of the ballot paper" />
          <div className="bp-title">{titleBn}</div>
        </div>
        <div className="bp-number">
          <span className="bp-number-label">ব্যালট পেপার নং</span>
          <span className="bp-number-box" title={ballotLabel ? `Ballot paper ${ballotLabel}` : undefined}>{ballotLabel ? toBengaliDigits(ballotLabel) : ""}</span>
        </div>
      </div>

      <table className="bp-table">
        <colgroup>
          <col style={{ width: "27.1%" }} /><col style={{ width: "12.9%" }} /><col style={{ width: "20.7%" }} />
          <col style={{ width: "26.3%" }} /><col style={{ width: "13%" }} />
        </colgroup>
        <thead>
          <tr>
            <HeadCell side="left" state={sideState.left} readOnly={readOnly} onSelectAll={onSelectAll} />
            <th className="bp-head bp-head-post">পদের নাম</th>
            <HeadCell side="right" state={sideState.right} readOnly={readOnly} onSelectAll={onSelectAll} />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.position.id}-${index}`}>
              <CandidateCells candidate={row.left} on={!!row.left && selected.has(row.left.id)} isNull={!!row.left && nullIds.has(row.left.id)} readOnly={readOnly} onToggle={onToggle} />
              {row.span > 0 && (
                <td className={`bp-post ${row.span > 1 ? "is-merged" : ""}`} rowSpan={row.span}>{row.position.name_bn ?? row.position.name_en}</td>
              )}
              <CandidateCells candidate={row.right} on={!!row.right && selected.has(row.right.id)} isNull={!!row.right && nullIds.has(row.right.id)} readOnly={readOnly} onToggle={onToggle} />
            </tr>
          ))}
        </tbody>
      </table>

      <div className="bp-foot">
        <div className="bp-rules">
          <div className="bp-rules-title">নির্দেশাবলীঃ</div>
          <div>ক) প্রতিটি পদের প্রার্থীর নামের পাশের বক্সে X দিয়ে ভোট দিন</div>
          <div>খ) X চিহ্ন যেন বক্সের মধ্যে থাকে। অন্যথায় ভোট বাতিল বলে গণ্য হবে।</div>
          <div>গ)&nbsp; X চিহ্ন ঘষা-মাজা করলে ভোট বাতিল বলে গণ্য হবে।</div>
        </div>
        <div className="bp-seal">
          <div>নির্বাচন কমিশনারঃ</div>
          <div>সীলঃ</div>
        </div>
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="bp-barcode" src={withBase("/ballot-barcode.png")} alt="Bar code of the ballot paper" />
    </div>
  );
}
