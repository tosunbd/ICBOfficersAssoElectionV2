"use client";

import { useCallback, useState, type FormEvent } from "react";
import { api, getApiBaseUrl } from "@/lib/api";
import { errorMessage, formatDateTime, roleLabel } from "@/lib/format";
import type { SystemStatus, UserAccount } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
import { useLoader } from "@/hooks/useLoader";
import { useToast } from "@/components/ui/Toast";
import { Modal } from "@/components/ui/Modal";
import { CardHead, PageHeader, Spinner } from "@/components/ui/Basics";
import { Icon, type IconName } from "@/components/ui/Icon";
import { ElectionTitleCard } from "@/components/admin/ElectionTitleCard";
import { DatabaseCard } from "@/components/admin/DatabaseCard";

const MIN_PASSWORD = 3;

/** Rough strength hint for the new password (display only; the server enforces its own rules). */
function strength(password: string): { score: number; label: string } {
  if (!password) return { score: 0, label: "" };
  let score = 0;
  if (password.length >= 6) score++;
  if (password.length >= 10) score++;
  if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score++;
  if (/\d/.test(password) && /[^A-Za-z0-9]/.test(password)) score++;
  score = Math.max(1, score);
  return { score, label: ["", "Weak", "Fair", "Good", "Strong"][score] };
}

export default function SettingsPage() {
  const { token, username, role, isAdmin, isSuperAdmin } = useAuth();
  const toast = useToast();
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [users, setUsers] = useState<UserAccount[]>([]);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resetting, setResetting] = useState<UserAccount | null>(null);
  const [resetValue, setResetValue] = useState("");

  const load = useCallback(async () => {
    if (!token || !isAdmin) return;
    try {
      const [status, accounts] = await Promise.all([api.admin.system(token), api.admin.users(token)]);
      setSystem(status);
      setUsers(accounts);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }, [token, isAdmin, toast]);

  useLoader(load);

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (!token) return;
    if (next !== confirm) { toast.error("New passwords do not match"); return; }
    setBusy(true);
    try {
      await api.auth.changePassword(token, current, next);
      toast.success("Password changed");
      setCurrent(""); setNext(""); setConfirm("");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const resetPassword = async (event: FormEvent) => {
    event.preventDefault();
    if (!token || !resetting) return;
    setBusy(true);
    try {
      await api.admin.resetPassword(token, resetting.id, resetValue);
      toast.success(`Password of ${resetting.username} changed`);
      setResetting(null);
      setResetValue("");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const meter = strength(next);
  const mismatch = confirm.length > 0 && next !== confirm;
  const rows: Array<{ label: string; icon: IconName; value: React.ReactNode }> = system ? [
    { label: "Version", icon: "sparkles", value: system.version },
    { label: "API URL", icon: "server", value: <code>{getApiBaseUrl()}</code> },
    { label: "Database file", icon: "file", value: <code>{system.database_file ?? "—"}</code> },
    { label: "Active election id", icon: "landmark", value: system.active_election_id ?? <span className="text-faint">none</span> },
    { label: "Ballot ranges", icon: "hash", value: Object.entries(system.entry_ranges).map(([name, span]) => `${name}: ${span}`).join(" · ") || "—" },
  ] : [];

  const passwordCard = (
    <div className="card">
      <CardHead icon="key" title="Change password" subtitle={`Signed in as ${username} · ${roleLabel(role)}`} gold />
      <form onSubmit={changePassword} className="flex flex-col gap-4">
        <div className="input-group"><label className="input-label" htmlFor="pw-current">Current password</label>
          <div className="input-wrap"><Icon name="lock" size={16} />
            <input id="pw-current" className="input" type={show ? "text" : "password"} autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            <button type="button" className="input-affix" onClick={() => setShow((v) => !v)} aria-label={show ? "Hide passwords" : "Show passwords"}><Icon name={show ? "eyeOff" : "eye"} size={15} /></button>
          </div></div>
        <div className="input-group"><label className="input-label" htmlFor="pw-next">New password</label>
          <div className="input-wrap"><Icon name="key" size={16} />
            <input id="pw-next" className="input" type={show ? "text" : "password"} autoComplete="new-password" minLength={MIN_PASSWORD} value={next} onChange={(e) => setNext(e.target.value)} required /></div>
          <div className={`strength s${meter.score}`}><span /><span /><span /><span /></div>
          <span className="input-hint">{meter.label ? `${meter.label} · ` : ""}Minimum {MIN_PASSWORD} characters; a longer one is safer</span>
        </div>
        <div className="input-group"><label className="input-label" htmlFor="pw-confirm">Repeat new password</label>
          <div className="input-wrap"><Icon name={mismatch ? "xCircle" : confirm && !mismatch ? "checkCircle" : "key"} size={16} />
            <input id="pw-confirm" className="input" type={show ? "text" : "password"} autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required
              style={mismatch ? { borderColor: "var(--color-error)" } : undefined} /></div>
          {mismatch && <span className="input-hint text-error">Passwords do not match yet</span>}
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? <><span className="btn-spinner" /> Updating…</> : <><Icon name="shield" size={16} /> Update password</>}
        </button>
      </form>
    </div>
  );

  // an Election Commissioner only has the own password here
  if (!isAdmin) {
    return (
      <div className="page">
        <PageHeader eyebrow="Account" title="Change password" subtitle="Your sign-in for the ballot entry desk" />
        <div style={{ maxWidth: 520 }}>{passwordCard}</div>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader eyebrow="System" title="Settings" subtitle="Election title, users, database, account and system information" />

      <ElectionTitleCard />

      <div className="card card-gold mb-6">
        <CardHead icon="users" title="Users" subtitle="The five accounts of the counting room" gold />
        <div className="table-wrapper">
          <table className="table">
            <thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Ballot numbers</th><th>Last sign-in</th><th></th></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td><span className="chip-no">{u.username}</span></td>
                  <td>{u.full_name ?? "—"}</td>
                  <td><span className={`badge ${u.role === "superadmin" ? "badge-accent" : u.role === "admin" ? "badge-primary" : "badge-success"}`}>{roleLabel(u.role)}</span></td>
                  <td>{u.ballot_from && u.ballot_to
                    ? <strong style={{ fontVariantNumeric: "tabular-nums" }}>{String(u.ballot_from).padStart(system?.ballot_number_digits ?? 3, "0")} – {String(u.ballot_to).padStart(system?.ballot_number_digits ?? 3, "0")}</strong>
                    : <span className="text-faint">views only</span>}</td>
                  <td className="text-faint text-small">{u.last_login_at ? formatDateTime(u.last_login_at) : "never"}</td>
                  <td className="cell-actions">
                    {isSuperAdmin && <button className="btn btn-ghost btn-sm" onClick={() => { setResetting(u); setResetValue(""); }}><Icon name="key" size={14} /> Set password</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-faint text-small mt-4">
          EC1, EC2 and EC3 enter the ballots of their own number range; SA and Admin watch the entry and print the reports.
          {isSuperAdmin ? " As Super Admin you can set a new password for any account." : " Only the Super Admin can set another user's password."}
          {" "}The ranges come from <code>ENTRY_RANGES</code> in the <code>.env</code> file.
        </p>
      </div>

      <DatabaseCard />

      <div className="two-columns">
        {passwordCard}
        <div className="card">
          <CardHead icon="server" title="System" subtitle="Read from the API server" />
          {!system ? <Spinner /> : (
            <div className="info-list stagger">
              {rows.map((row) => (
                <div className="info-row" key={row.label}>
                  <span className="info-row-icon"><Icon name={row.icon} size={16} /></span>
                  <div style={{ minWidth: 0 }}><div className="info-row-label">{row.label}</div><div className="info-row-value">{row.value}</div></div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <Modal open={resetting !== null} title={`Set a new password for ${resetting?.username ?? ""}`} onClose={() => setResetting(null)}>
        <form onSubmit={resetPassword} className="flex flex-col gap-4">
          <p className="text-muted text-small">{resetting?.full_name} will sign in with this password from now on. The change is written to the audit log.</p>
          <div className="input-group"><label className="input-label" htmlFor="pw-reset">New password</label>
            <div className="input-wrap"><Icon name="key" size={16} />
              <input id="pw-reset" className="input" type="text" autoComplete="off" minLength={MIN_PASSWORD} value={resetValue} onChange={(e) => setResetValue(e.target.value)} required autoFocus /></div>
          </div>
          <div className="flex gap-2" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-ghost" onClick={() => setResetting(null)} disabled={busy}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={busy || resetValue.length < MIN_PASSWORD}><Icon name="shield" size={16} /> Set password</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
