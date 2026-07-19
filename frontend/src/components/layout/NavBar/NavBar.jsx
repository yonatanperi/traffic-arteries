import { NavLink } from "react-router-dom";
import { SegmentedNav } from "../../ui/SegmentedControl";
import Button from "../../ui/Button";
import { IconRoute, IconBranch, IconHub, IconUser, IconLock, IconLogout } from "../../ui/icons/icons.jsx";
import { useAuth } from "../../../hooks/useAuth.js";
import "./NavBar.css";

const ALL_LINKS = [
  { to: "/", label: "בניית ציר תנועה", end: true, icon: IconRoute },
  { to: "/routes", label: "עריכת צירים", roles: ["editor", "admin"], icon: IconBranch },
  { to: "/brain", label: "הצצה למוח", roles: ["editor", "admin"], icon: IconHub },
  { to: "/users", label: "ניהול משתמשים", roles: ["editor", "admin"], icon: IconUser },
];

export default function NavBar() {
  const { isAuthenticated, user, role, logout } = useAuth();
  const links = ALL_LINKS.filter((l) => !l.roles || l.roles.includes(role));

  return (
    <>
      <header className="navbar">
        <div className="navbar-inner">
          {isAuthenticated && (
            <span className="navbar-hello">שלום, {user.first_name}</span>
          )}
          <div className="navbar-links">
            <SegmentedNav items={links} activeExtraClassName="nav-link--active" />
          </div>

          <div className="navbar-auth">
            {isAuthenticated ? (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  className="navbar-auth-btn"
                  onClick={logout}
                >
                  התנתקות
                </Button>
              </>
            ) : (
              <>
                <Button
                  size="sm"
                  as={NavLink}
                  to="/login"
                  variant="ghost"
                  className="navbar-auth-btn"
                >
                  התחברות
                </Button>
                <Button
                  size="sm"
                  as={NavLink}
                  to="/register"
                  variant="ghost"
                  className="navbar-auth-btn"
                >
                  הרשמה
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <nav className="tabbar" aria-label="ניווט ראשי">
        {links.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            aria-label={item.label}
            className={({ isActive }) =>
              "tabbar-item" + (isActive ? " tabbar-item--on" : "")
            }
          >
            <item.icon size={24} />
          </NavLink>
        ))}

        {isAuthenticated ? (
          <button
            type="button"
            className="tabbar-item"
            aria-label="התנתקות"
            onClick={logout}
          >
            <IconLogout size={24} />
          </button>
        ) : (
          <NavLink
            to="/login"
            aria-label="כניסה"
            className={({ isActive }) =>
              "tabbar-item" + (isActive ? " tabbar-item--on" : "")
            }
          >
            <IconLock size={24} />
          </NavLink>
        )}
      </nav>
    </>
  );
}
