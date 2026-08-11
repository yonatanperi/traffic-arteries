import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import Logo from "../Logo";
import Button from "../../ui/Button";
import IconButton from "../../ui/IconButton";
import { IconMenu, IconClose, IconUser, IconLogout } from "../../ui/icons";
import { useAuth } from "../../../hooks/useAuth.js";
import "./MobileTopBar.css";

/**
 * The phone-width chrome: mark at the inline start, auth action and (only when
 * there is somewhere else to go) a hamburger at the inline end. Rendered
 * alongside the desktop navbar by NavBar, which owns the role-filtered `links`
 * and shows exactly one of the two per breakpoint.
 *
 * Deliberately *not* sticky: it scrolls away with the page so the home page's
 * trip bar is the only thing pinned to the top of a results list.
 */
export default function MobileTopBar({ links }) {
  const { isAuthenticated, user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  // A guest only ever has the home link — a menu holding one item people are
  // already looking at is just a button that does nothing.
  const hasMenu = links.length > 1;

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <header className="mtopbar">
      <NavLink to="/" className="mtopbar-brand" aria-label="צירי תנועה — לדף הבית">
        <Logo size={34} />
      </NavLink>

      <div className="mtopbar-actions">
        {isAuthenticated ? (
          <Button
            size="sm"
            variant="ghost"
            className="mtopbar-auth"
            onClick={logout}
          >
            <IconLogout size={16} />
            התנתקות
          </Button>
        ) : (
          <Button
            size="sm"
            as={NavLink}
            to="/login"
            variant="ghost"
            className="mtopbar-auth"
          >
            <IconUser size={16} />
            התחברות
          </Button>
        )}

        {hasMenu && (
          <IconButton
            size="lg"
            className="mtopbar-menu-btn"
            ariaLabel={open ? "סגירת התפריט" : "פתיחת התפריט"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <IconClose size={22} /> : <IconMenu size={22} />}
          </IconButton>
        )}
      </div>

      {open && (
        <>
          <div
            className="mtopbar-scrim"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          {/* Absolutely placed against the bar itself, so it stays attached
              without measuring anything when the bar has been scrolled. */}
          <nav className="mtopbar-menu" aria-label="ניווט ראשי">
            {isAuthenticated && (
              <p className="mtopbar-menu-hello">שלום, {user.first_name}</p>
            )}
            {links.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  "mtopbar-menu-item" + (isActive ? " mtopbar-menu-item--on" : "")
                }
                onClick={() => setOpen(false)}
              >
                <item.icon size={18} />
                {item.label}
              </NavLink>
            ))}
          </nav>
        </>
      )}
    </header>
  );
}
