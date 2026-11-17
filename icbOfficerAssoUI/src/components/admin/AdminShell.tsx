"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useElection } from "@/hooks/useElection";
import { useTheme } from "@/hooks/useTheme";
import { ElectionStatusBadge, Spinner, initials } from "@/components/ui/Basics";
import { roleLabel } from "@/lib/format";
import { Logo } from "@/components/ui/Logo";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { Icon, type IconName } from "@/components/ui/Icon";
import { useClock } from "@/components/ui/Motion";
import { withBase } from "@/lib/basePath";
import { CommandPalette, type PaletteCommand } from "./CommandPalette";

interface NavItem { href: string; icon: IconName; label: string; keywords?: string }

/** Election Commissioners only enter ballots (and can change their own password). */
const EC_NAV: Array<{ group: string; items: NavItem[] }> = [
  { group: "Counting", items: [
    { href: "/admin/entry", icon: "ballot", label: "Ballot Entry", keywords: "form save vote" },
  ] },
  { group: "Account", items: [
    { href: "/admin/settings", icon: "key", label: "Change password", keywords: "account" },
  ] },
];
const EC_PATHS = ["/admin/entry", "/admin/settings"];

const NAV: Array<{ group: string; items: NavItem[] }> = [
  { group: "Command", items: [
    { href: "/admin", icon: "overview", label: "Overview", keywords: "home dashboard" },
    { href: "/admin/entry", icon: "activity", label: "Ballot Entry · Live", keywords: "monitor desk ec1 ec2 ec3 form" },
    { href: "/admin/results", icon: "chart", label: "Results & Controls", keywords: "publish pause recount export" },
    { href: "/admin/reports", icon: "scroll", label: "Reports", keywords: "print pdf summary tally winner signature" },
  ] },
  { group: "Election", items: [
    { href: "/admin/elections", icon: "landmark", label: "Elections", keywords: "positions status" },
    { href: "/admin/candidates", icon: "users", label: "Candidates" },
    { href: "/admin/ballots", icon: "ballot", label: "Ballots", keywords: "register entered null corrected" },
  ] },
  { group: "System", items: [
    { href: "/admin/audit", icon: "scroll", label: "Audit Log", keywords: "history" },
    { href: "/admin/settings", icon: "settings", label: "Settings", keywords: "password users system" },
  ] },
];

/** Sidebar + top bar around every admin page; redirects to login when signed out. */
export function AdminShell({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, username, role, isEc, logout } = useAuth();
  const nav = isEc ? EC_NAV : NAV;
  const home = isEc ? "/admin/entry" : "/admin";
  const { elections, election, selectElection, loading } = useElection();
  const { toggleTheme } = useTheme();
  const pathname = usePathname();
  const router = useRouter();
  const clock = useClock({ hour: "2-digit", minute: "2-digit" });
  const [menuOpen, setMenuOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const signingOut = useRef(false);

  /** Sign out and land on the login page with a confirmation message. */
  const signOut = useCallback(() => {
    signingOut.current = true;
    logout();
    router.replace("/admin/login?signedout=1");
  }, [logout, router]);

  useEffect(() => {
    if (!isLoading && !isAuthenticated && !signingOut.current) router.replace("/admin/login");
  }, [isLoading, isAuthenticated, router]);

  // an Election Commissioner only has the entry form
  const ecBlocked = isEc && !EC_PATHS.some((path) => pathname.startsWith(path));
  useEffect(() => {
    if (!isLoading && isAuthenticated && ecBlocked) router.replace("/admin/entry");
  }, [isLoading, isAuthenticated, ecBlocked, router]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const commands = useMemo<PaletteCommand[]>(() => [
    ...nav.flatMap(({ items }) => items.map((item) => ({
      id: item.href, label: item.label, group: "Go to", icon: item.icon, keywords: item.keywords, run: () => router.push(item.href),
    }))),
    { id: "live", label: "Open the public dashboard", group: "Actions", icon: "broadcast", hint: "new tab", keywords: "dashboard projector", run: () => window.open(withBase("/dashboard"), "_blank") },
    { id: "theme", label: "Toggle light / dark theme", group: "Actions", icon: "moon", keywords: "appearance", run: toggleTheme },
    { id: "logout", label: "Sign out", group: "Actions", icon: "logout", keywords: "logout log out", run: signOut },
  ], [nav, router, toggleTheme, signOut]);

  if (isLoading || !isAuthenticated || ecBlocked) return <Spinner label="Checking session…" />;

  const isActive = (href: string) => (href === "/admin" ? pathname === "/admin" : pathname.startsWith(href));

  return (
    <div className="admin-layout">
      {menuOpen && <div className="sidebar-scrim" onClick={() => setMenuOpen(false)} />}
      <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
        <Link href={home} className="sidebar-brand" onClick={() => setMenuOpen(false)}>
          <Logo size={46} />
          <div>
            <div className="sidebar-brand-name">ICB Election</div>
            <div className="sidebar-brand-sub">{isEc ? "Entry Desk" : "Control Room"}</div>
          </div>
        </Link>

        <button className="sidebar-search" onClick={() => setPaletteOpen(true)}>
          <Icon name="search" size={15} /> Quick jump… <span className="kbd">Ctrl K</span>
        </button>

        {nav.map(({ group, items }) => (
          <div className="nav-group" key={group}>
            <div className="nav-group-label">{group}</div>
            <nav className="sidebar-nav">
              {items.map((item) => (
                <Link key={item.href} href={item.href} onClick={() => setMenuOpen(false)} className={`sidebar-link ${isActive(item.href) ? "active" : ""}`}>
                  <Icon name={item.icon} size={19} />
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        ))}

        <div className="sidebar-footer">
          <Link href="/dashboard" target="_blank" className="btn btn-accent btn-block">
            <Icon name="broadcast" size={16} /> Open dashboard
          </Link>
          <div className="user-card">
            <span className="avatar">{initials(username)}</span>
            <div style={{ minWidth: 0 }}>
              <div className="user-card-name">{username}</div>
              <div className="user-card-role">{roleLabel(role)}</div>
            </div>
            <button className="btn btn-ghost btn-sm btn-icon" onClick={signOut} title="Sign out" aria-label="Sign out"><Icon name="logout" size={15} /></button>
          </div>
        </div>
      </aside>

      <div className="admin-main">
        <header className="topbar">
          <button className="btn btn-ghost btn-icon menu-btn" onClick={() => setMenuOpen((v) => !v)} aria-label="Menu"><Icon name="menu" /></button>
          {!isEc && !loading && elections.length > 0 && (
            <div className="topbar-election">
              <span className="topbar-election-label">Election</span>
              <select className="input input-sm topbar-select" value={election?.id ?? ""} onChange={(e) => selectElection(Number(e.target.value))} aria-label="Election">
                {elections.map((e) => <option key={e.id} value={e.id}>{e.title} ({e.year})</option>)}
              </select>
              {election && <ElectionStatusBadge status={election.status} />}
            </div>
          )}
          {!isEc && election && (
            <div className="flex gap-2 flex-wrap">
              <span className={`badge ${election.dashboard_published ? "badge-success" : "badge-muted"}`}>
                <Icon name={election.dashboard_published ? "eye" : "eyeOff"} strokeWidth={2.2} />{election.dashboard_published ? "Published" : "Hidden"}
              </span>
              <span className={`badge ${election.dashboard_paused ? "badge-warning" : "badge-primary"}`}>
                <Icon name={election.dashboard_paused ? "pause" : "activity"} strokeWidth={2.2} />{election.dashboard_paused ? "Paused" : "Live"}
              </span>
            </div>
          )}
          <span className="topbar-spacer" />
          <span className="topbar-clock"><Icon name="clock" size={14} />{clock}</span>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={() => setPaletteOpen(true)} title="Search (Ctrl+K)" aria-label="Search"><Icon name="search" size={16} /></button>
          <ThemeToggle compact />
          <UserMenu username={username} role={role} onSignOut={signOut} />
        </header>

        <main className="admin-content">{children}</main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={commands} />
    </div>
  );
}

/** Avatar button in the top bar with account links and Sign out. */
function UserMenu({ username, role, onSignOut }: { username: string | null; role: string | null; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);

  return (
    <div className="user-menu" ref={box}>
      <button className={`user-menu-trigger ${open ? "open" : ""}`} onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open}>
        <span className="avatar avatar-sm">{initials(username)}</span>
        <span className="user-menu-name">{username}</span>
        <Icon name="chevronDown" size={14} />
      </button>
      {open && (
        <div className="user-menu-panel" role="menu">
          <div className="user-menu-head">
            <span className="avatar">{initials(username)}</span>
            <div>
              <div className="user-card-name">{username}</div>
              <div className="user-card-role"><span className="live-dot" style={{ width: 6, height: 6, display: "inline-block", marginRight: 6 }} />Signed in · {roleLabel(role)}</div>
            </div>
          </div>
          <Link href="/admin/settings" className="user-menu-item" role="menuitem" onClick={() => setOpen(false)}><Icon name="key" size={15} /> Change password</Link>
          <Link href="/dashboard" target="_blank" className="user-menu-item" role="menuitem" onClick={() => setOpen(false)}><Icon name="broadcast" size={15} /> Open dashboard</Link>
          <div className="user-menu-sep" />
          <button className="user-menu-item danger" role="menuitem" onClick={onSignOut}><Icon name="logout" size={15} /> Sign out</button>
        </div>
      )}
    </div>
  );
}
