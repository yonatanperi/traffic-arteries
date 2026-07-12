import { NavLink } from "react-router-dom";
import { SegmentedNav } from "../../ui/SegmentedControl";
import { useAuth } from "../../../hooks/useAuth.js";
import "./NavBar.css";

const ALL_LINKS = [
  { to: "/", label: "בניית ציר תנועה", end: true },
  { to: "/routes", label: "עריכת צירים", roles: ["editor", "admin"] },
  { to: "/brain", label: "הצצה למוח", roles: ["editor", "admin"] },
  { to: "/users", label: "ניהול משתמשים", roles: ["editor", "admin"] },
];

export default function NavBar() {
  const { isAuthenticated, user, role, logout } = useAuth();
  const links = ALL_LINKS.filter((l) => !l.roles || l.roles.includes(role));

  return (
    <header className="navbar">
      <div className="navbar-inner">
        <div className="navbar-links">
          <SegmentedNav items={links} activeExtraClassName="nav-link--active" />
        </div>

        <div className="navbar-auth">
          {isAuthenticated ? (
            <>
              <span className="navbar-hello">שלום, {user.first_name}</span>
              <button type="button" className="btn btn-ghost navbar-auth-btn" onClick={logout}>
                התנתקות
              </button>
            </>
          ) : (
            <>
              <NavLink to="/login" className="btn btn-ghost navbar-auth-btn">
                התחברות
              </NavLink>
              <NavLink to="/register" className="btn btn-primary navbar-auth-btn">
                הרשמה
              </NavLink>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
