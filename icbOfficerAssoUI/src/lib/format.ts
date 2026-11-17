import type { BallotStatus, ElectionStatus, Role } from "./types";

/** API timestamps are naive UTC; make them explicit before formatting. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const iso = /[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export const BALLOT_STATUS_LABEL: Record<BallotStatus, string> = {
  processing: "Processing",
  processed: "Entered",
  needs_review: "Needs review",
  reviewed: "Corrected",
  error: "Error",
};

export const BALLOT_STATUS_BADGE: Record<BallotStatus, string> = {
  processing: "badge-info",
  processed: "badge-success",
  needs_review: "badge-warning",
  reviewed: "badge-primary",
  error: "badge-error",
};

export const ELECTION_STATUS_BADGE: Record<ElectionStatus, string> = {
  draft: "badge-info",
  active: "badge-success",
  completed: "badge-accent",
};

export function errorMessage(error: unknown, fallback = "Something went wrong"): string {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export const ROLE_LABEL: Record<Role, string> = {
  superadmin: "Super Admin",
  admin: "Admin",
  ec: "Election Commissioner",
};

export function roleLabel(role: string | null | undefined): string {
  return ROLE_LABEL[role as Role] ?? "User";
}

export const isAdminRole = (role: string | null | undefined) => role === "superadmin" || role === "admin";

/** 7 -> "007" */
export function ballotLabel(ballotNo: number, digits = 3): string {
  return String(ballotNo).padStart(digits, "0");
}

const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
export function toBengaliDigits(value: number | string): string {
  return String(value).replace(/\d/g, (d) => BN_DIGITS[Number(d)]);
}
