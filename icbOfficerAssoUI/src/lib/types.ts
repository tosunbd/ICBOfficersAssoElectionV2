/**
 * TypeScript mirrors of the backend Pydantic schemas (icbOfficerAssoAPI/app/schemas).
 * Keep these in sync when the API changes.
 */

export type ElectionStatus = "draft" | "active" | "completed";
export type BallotStatus = "processing" | "processed" | "needs_review" | "reviewed" | "error";

export interface Election {
  id: number;
  title: string;
  title_bn: string | null;
  year: number;
  description: string | null;
  status: ElectionStatus;
  dashboard_published: boolean;
  dashboard_paused: boolean;
  /** PAUSE pressed on the live screen: no ballot is read until START. */
  counting_paused?: boolean;
  total_voters: number;
  /** Seconds the public screen shows each ballot (live count and the replay after Publish). */
  ballot_display_seconds: number;
  created_at: string;
  updated_at: string;
}

export interface Position {
  id: number;
  election_id: number;
  position_order: number;
  name_en: string;
  name_bn: string | null;
  max_selections: number;
  created_at: string;
}

export interface ElectionDetail extends Election {
  positions: Position[];
}

export interface Candidate {
  id: number;
  position_id: number;
  election_id: number;
  voter_no: string;
  name_en: string;
  name_bn: string | null;
  display_order: number;
  vote_count: number;
  created_at: string;
}

export interface Vote {
  id: number;
  ballot_id: number;
  candidate_id: number;
  position_id: number;
  is_valid: boolean;
  invalid_reason: string | null;
  confidence_score: number;
  created_at: string;
}

export interface Ballot {
  id: number;
  election_id: number;
  ballot_no: number | null;
  ballot_paper_no: string | null;
  pdf_filename: string;
  page_number: number;
  source: string;
  status: BallotStatus;
  error_message: string | null;
  /** Why marks were not counted (null votes). */
  ocr_warnings: string[];
  /** Boxes marked on the paper. */
  boxes_detected: number;
  boxes_expected: number;
  /** Votes that count. */
  total_votes_extracted: number;
  is_valid: boolean;
  entered_by: string | null;
  corrected_by: string | null;
  approved_by: string | null;
  has_preview: boolean;
  scanned_at: string;
  processed_at: string | null;
  reviewed_at: string | null;
}

export interface BallotDetail extends Ballot {
  votes: Vote[];
}

export interface BallotList {
  ballots: Ballot[];
  total: number;
  page: number;
  per_page: number;
}

export interface CandidateResult {
  candidate_id: number;
  voter_no: string;
  name_en: string;
  name_bn: string | null;
  vote_count: number;
  percentage: number;
  rank: number;
  is_leading: boolean;
}

export interface PositionResult {
  position_id: number;
  position_order: number;
  name_en: string;
  name_bn: string | null;
  max_selections: number;
  total_votes_cast: number;
  candidates: CandidateResult[];
}

export interface DashboardStats {
  total_ballots: number;
  counted_ballots: number;
  processed_ballots: number;
  needs_review_ballots: number;
  reviewed_ballots: number;
  error_ballots: number;
  pending_ballots: number;
  total_voters: number;
  turnout_percentage: number;
}

export interface DashboardData {
  election_id: number;
  election_title: string;
  election_title_bn: string | null;
  election_year: number;
  election_status: ElectionStatus;
  dashboard_published: boolean;
  dashboard_paused: boolean;
  /** PAUSE pressed on the live screen: no ballot is read until START. */
  counting_paused?: boolean;
  results_visible: boolean;
  stats: DashboardStats;
  positions: PositionResult[];
}

export interface ActiveElection {
  id: number;
  title: string;
  title_bn: string | null;
  year: number;
  status: ElectionStatus;
  dashboard_published: boolean;
  dashboard_paused: boolean;
  /** PAUSE pressed on the live screen: no ballot is read until START. */
  counting_paused?: boolean;
  live_display_seconds: number;
}

export interface AuditLogEntry {
  id: number;
  admin_user_id: number | null;
  username: string | null;
  action: string;
  details: string | null;
  created_at: string | null;
}

export interface SystemStatus {
  version: string;
  active_election_id: number | null;
  database_file: string | null;
  /** {"EC1": "001-150", ...} */
  entry_ranges: Record<string, string>;
  ballot_number_digits: number;
  total_users: number;
}

export type Role = "superadmin" | "admin" | "ec";

export interface UserAccount {
  id: number;
  username: string;
  full_name: string | null;
  role: Role;
  ballot_from: number | null;
  ballot_to: number | null;
  last_login_at: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username: string;
  full_name: string | null;
  role: Role;
  ballot_from: number | null;
  ballot_to: number | null;
}

export interface DatabaseFile {
  year: number;
  file_name: string;
  size_bytes: number;
  modified_at: string;
  current: boolean;
}

/** The database file in use (one per election year) and the others next to it. */
export interface DatabaseInfo {
  year: number;
  per_year: boolean;
  file_name: string | null;
  path: string | null;
  size_bytes: number | null;
  files: DatabaseFile[];
}

/* ------------------------------------------------ Admin -> Reports */

export interface ReportCandidate {
  candidate_id: number;
  voter_no: string;
  name_en: string;
  name_bn: string | null;
  display_order: number;
  panel: "left" | "right" | "";    // side of the ballot paper the name is printed on
  votes: number;
  percentage: number;
  rank: number;
  outcome: "elected" | "tie" | "";
}

export interface ReportPosition {
  position_id: number;
  position_order: number;
  name_en: string;
  name_bn: string | null;
  max_selections: number;
  total_votes: number;
  candidates: ReportCandidate[];   // by votes, highest first
}

/** A box marked on a ballot that is not counted (Null Votes report). */
export interface ReportVoidMark {
  candidate_id: number;
  position_id: number;
  reason: string;
}

export interface ReportBallot {
  ballot_id: number;
  serial: number;
  ballot_paper_no: string | null;
  pdf_filename: string;
  page_number: number;
  status: string;
  is_valid: boolean;
  candidate_ids: number[];         // the 1s of this row
  void_marks: number;
  void: ReportVoidMark[];
}

export interface ElectionReport {
  election_id: number;
  title: string;
  title_bn: string | null;
  year: number;
  status: string;
  total_voters: number;
  generated_at: string;
  stats: DashboardStats;
  manual_ballots: number;  // selections saved by the Election Commission (reviewed)
  total_votes: number;
  void_marks: number;
  positions: ReportPosition[];
  ballots: ReportBallot[];
}

/* ------------------------------------------------ Ballot entry */

export interface NullPost {
  position_id: number;
  name_en: string;
  name_bn: string | null;
  marked: number;
  allowed: number;
}

/** A change to a saved ballot, kept apart until the Super Admin or the Admin decides on it. */
export interface Correction {
  id: number;
  ballot_id: number;
  ballot_no: number;
  label: string;
  status: "pending" | "approved" | "rejected" | "withdrawn";
  requested_by: string;
  requested_at: string;
  decided_by: string | null;
  decided_at: string | null;
  candidate_ids: number[];           // the boxes as they should be
  previous_candidate_ids: number[];  // the boxes saved when the request was made
  counted: number;
  null_marks: number;
  previous_counted: number;
  previous_null_marks: number;
}

export interface DecisionResult {
  correction: Correction;
  ballot: EntryBallot;
}

/** One saved ballot exactly as entered. */
export interface EntryBallot {
  ballot_id: number;
  ballot_no: number;
  label: string;                 // "001"
  status: BallotStatus;          // processed (entered) | reviewed (corrected)
  entered_by: string | null;
  entered_at: string | null;
  corrected_by: string | null;
  corrected_at: string | null;
  approved_by: string | null;
  candidate_ids: number[];       // every box marked on the paper
  null_candidate_ids: number[];  // marked but not counted
  counted: number;
  null_marks: number;
  null_posts: NullPost[];
  /** A correction of this ballot is waiting for approval. */
  pending: Correction | null;
}

export interface DeskDraft {
  ballot_no: number;
  label: string;
  candidate_ids: number[];
  editing: boolean;
  updated_at: string;
}

/** One Election Commissioner's entry desk. */
export interface Desk {
  username: string;
  full_name: string | null;
  ballot_from: number;
  ballot_to: number;
  total: number;
  entered: number;
  next_ballot_no: number | null;   // null = the whole range is entered
  next_label: string | null;
  online: boolean;
  draft: DeskDraft | null;
  last_ballot_no: number | null;
  last_label: string | null;
  last_saved_at: string | null;
  pending_corrections: number;
}

export interface EntryElection {
  id: number;
  title: string;
  title_bn: string | null;
  year: number;
  status: ElectionStatus;
  counting_paused: boolean;
  total_voters: number;
}

export interface EntryState {
  election: EntryElection | null;
  digits: number;
  desks: Desk[];
  me: string | null;
  total_entered: number;
  total_ballots: number;
  /** Corrections waiting for the Super Admin / Admin. */
  pending_corrections: number;
  server_time: string;
}

export interface SaveResult {
  ballot: EntryBallot;
  desk: Desk;
}
