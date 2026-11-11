import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { DegradedBanner } from "../components/DegradedBanner";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuth } from "../lib/auth";
import { useApprovals } from "../lib/queries";

const LINKS: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Job inbox", end: true },
  { to: "/approvals", label: "Approvals" },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/messages", label: "Messages" },
  { to: "/runs", label: "Agent runs" },
  { to: "/analytics", label: "Analytics" },
  { to: "/settings", label: "Settings" },
];

export function Shell() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const approvals = useApprovals();
  const pending = approvals.data?.pending_count ?? 0;

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <DegradedBanner />
      <div className="shell">
        <header className="topbar">
          <Link to="/" className="brand">
            Gig<i>Bid</i>
          </Link>
          <button className="btn sm" aria-expanded={open} aria-controls="primary-nav" onClick={() => setOpen((o) => !o)} data-testid="menu-button">
            {open ? "Close" : "Menu"}
            {pending ? <span className="count" aria-label={`${pending} pending approvals`}>{pending}</span> : null}
          </button>
        </header>
        <nav id="primary-nav" className="nav" aria-label="Primary" data-open={open}>
          <Link to="/" className="brand">
            Gig<i>Bid</i> <small>copilot</small>
          </Link>
          <ul className="nav-list">
            {LINKS.map((l) => (
              <li key={l.to}>
                <NavLink to={l.to} end={l.end} className="nav-link">
                  {l.label}
                  {l.to === "/approvals" && pending ? (
                    <span className="count" data-testid="pending-count" aria-label={`${pending} pending`}>
                      {pending}
                    </span>
                  ) : null}
                </NavLink>
              </li>
            ))}
          </ul>
          <div className="nav-foot">
            <span>
              Signed in as <strong>{user?.email}</strong>
            </span>
            <div className="btn-row">
              <ThemeToggle />
              <button
                className="btn sm"
                onClick={() => {
                  void signOut().then(() => navigate("/sign-in"));
                }}
              >
                Sign out
              </button>
            </div>
          </div>
        </nav>
        <main id="main" className="main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </>
  );
}
