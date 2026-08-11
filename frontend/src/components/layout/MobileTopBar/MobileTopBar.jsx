import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import IconButton from "../../ui/IconButton";
import { IconMenu, IconClose, IconLogout } from "../../ui/icons";
import { useAuth } from "../../../hooks/useAuth.js";
import "./MobileTopBar.css";

/**
 * The phone-width chrome for a *signed-in* user — NavBar renders this one only
 * then, and leaves a guest the desktop bar, which already fits a phone.
 *
 * The bar is exactly the desktop navbar's greeting and nothing else; every
 * action (the sections, and the logout) lives behind the hamburger, so it stays
 * a greeting and one control however many sections a role unlocks.
 *
 * Deliberately *not* sticky: it scrolls away with the page so the home page's
 * trip bar is the only thing pinned to the top of a results list.
 */
export default function MobileTopBar({ links }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

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
      <span className="mtopbar-hello">שלום, {user.first_name}</span>

      <div className="mtopbar-actions">
        <IconButton
          size="lg"
          className="mtopbar-menu-btn"
          ariaLabel={open ? "סגירת התפריט" : "פתיחת התפריט"}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <IconClose size={22} /> : <IconMenu size={22} />}
        </IconButton>
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

            {/* Leaving the account is a section of this menu too — it is the
                one thing the bar itself has no room to keep. */}
            <button
              type="button"
              className="mtopbar-menu-item mtopbar-menu-item--out"
              onClick={() => {
                setOpen(false);
                logout();
              }}
            >
              <IconLogout size={18} />
              התנתקות
            </button>
          </nav>
        </>
      )}
    </header>
  );
}
