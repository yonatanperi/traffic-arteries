import { NavLink } from "react-router-dom";
import { SegmentedNav } from "../../ui/SegmentedControl";
import Button from "../../ui/Button";
import MobileTopBar from "../MobileTopBar";
import { IconRoute, IconBranch, IconHub, IconUser } from "../../ui/icons/icons.jsx";
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
      {/* On a phone the two bars are mutually exclusive, and which one shows
          depends on the user, not only on the width: a guest has just the home
          link and two auth buttons, which is exactly what the desktop bar
          already is and it fits — so they get it verbatim. A signed-in user has
          sections, a greeting and a logout, which don't, so they get the
          compact bar and its menu (see NavBar.css / MobileTopBar). */}
      <header className={"navbar" + (isAuthenticated ? "" : " navbar--phone")}>
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

      {isAuthenticated && <MobileTopBar links={links} />}
    </>
  );
}
