import { NavLink } from "react-router-dom";
import { SegmentedNav } from "../../ui/SegmentedControl";
import Button from "../../ui/Button";
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
              <Button variant="ghost" className="navbar-auth-btn" onClick={logout}>
                התנתקות
              </Button>
            </>
          ) : (
            <>
              <Button as={NavLink} to="/login" variant="ghost" className="navbar-auth-btn">
                התחברות
              </Button>
              <Button as={NavLink} to="/register" variant="primary" className="navbar-auth-btn">
                הרשמה
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
