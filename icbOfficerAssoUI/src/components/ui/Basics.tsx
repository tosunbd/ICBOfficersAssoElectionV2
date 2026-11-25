"use client";

import { useState, type InputHTMLAttributes, type ReactNode } from "react";
import { BALLOT_STATUS_BADGE, BALLOT_STATUS_LABEL, ELECTION_STATUS_BADGE, parseNumber } from "@/lib/format";
import type { BallotStatus, ElectionStatus } from "@/lib/types";
import { Icon, type IconName } from "./Icon";

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="centered-block">
      <div className="spinner" />
      {label && <p className="text-muted mt-4 text-small">{label}</p>}
    </div>
  );
}

export function Skeleton({ height = 16, width = "100%", style }: { height?: number | string; width?: number | string; style?: React.CSSProperties }) {
  return <div className="skeleton" style={{ height, width, ...style }} />;
}

export function EmptyState({ icon = "inbox", title, children }: { icon?: IconName; title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon"><Icon name={icon} size={34} strokeWidth={1.5} /></div>
      <h4>{title}</h4>
      {children && <div className="text-muted mt-4">{children}</div>}
    </div>
  );
}

const BALLOT_STATUS_ICON: Record<BallotStatus, IconName> = {
  processing: "refresh",
  processed: "check",
  needs_review: "alert",
  reviewed: "shield",
  error: "xCircle",
};

export function BallotStatusBadge({ status }: { status: BallotStatus }) {
  return (
    <span className={`badge ${BALLOT_STATUS_BADGE[status] ?? "badge-info"}`}>
      <Icon name={BALLOT_STATUS_ICON[status] ?? "info"} strokeWidth={2.4} />
      {BALLOT_STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function ElectionStatusBadge({ status }: { status: ElectionStatus }) {
  return (
    <span className={`badge badge-dot ${ELECTION_STATUS_BADGE[status] ?? "badge-info"} ${status === "active" ? "pulse" : ""}`} style={{ textTransform: "capitalize" }}>
      {status}
    </span>
  );
}

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: string; subtitle?: string; actions?: ReactNode; eyebrow?: string }) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

const ALERT_ICON: Record<string, IconName> = { info: "info", warning: "alert", error: "xCircle", success: "checkCircle" };

export function Alert({ type = "info", children }: { type?: "info" | "warning" | "error" | "success"; children: ReactNode }) {
  return (
    <div className={`alert alert-${type}`} role={type === "error" ? "alert" : undefined}>
      <Icon name={ALERT_ICON[type]} size={18} />
      <div className="alert-body">{children}</div>
    </div>
  );
}

/** Card heading with an icon tile, title, optional subtitle and right-hand actions. */
export function CardHead({ icon, title, subtitle, gold, children }: { icon: IconName; title: ReactNode; subtitle?: ReactNode; gold?: boolean; children?: ReactNode }) {
  return (
    <div className="card-head">
      <div className="card-title">
        <span className={`card-title-icon ${gold ? "gold" : ""}`}><Icon name={icon} size={18} /></span>
        <div>
          <div>{title}</div>
          {subtitle && <div className="card-subtitle">{subtitle}</div>}
        </div>
      </div>
      {children && <div className="flex gap-2 items-center flex-wrap">{children}</div>}
    </div>
  );
}

/** Accessible on/off switch with a label and optional description. */
export function Switch({ checked, onChange, label, description, gold, disabled }: {
  checked: boolean; onChange: () => void; label: ReactNode; description?: ReactNode; gold?: boolean; disabled?: boolean;
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} className={`switch ${gold ? "gold" : ""}`} onClick={onChange} disabled={disabled}>
      <span className="switch-track" aria-hidden="true" />
      <span className="switch-text">{label}{description && <small>{description}</small>}</span>
    </button>
  );
}

/**
 * Whole-number field that understands Bangla (০-৯) and English (0-9) digits,
 * also mixed.  Used instead of <input type="number">, which drops Bangla
 * digits.  What was typed stays on screen; onChange gets the number.
 */
export function NumberInput({ value, onChange, ...rest }: {
  value: number; onChange: (value: number) => void;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type">) {
  const [text, setText] = useState(String(value));
  // follow a value set from outside (a form reset, another field) unless the typed text already means it
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    if (parseNumber(text) !== value) setText(String(value));
  }
  return (
    <input
      {...rest} type="text" inputMode="numeric" autoComplete="off" value={text}
      onChange={(e) => {
        const cleaned = e.target.value.replace(/[^0-9০-৯]/g, "");  // digits of either script
        setText(cleaned);
        const n = parseNumber(cleaned);
        if (n !== null) { setSeen(n); onChange(n); }
      }}
      onBlur={(e) => {
        if (parseNumber(text) === null) setText(String(value));  // an emptied field shows the number in use
        rest.onBlur?.(e);
      }}
    />
  );
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.replace(/^(mr|mrs|ms|dr|md)\.?\s+/i, "").trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}
