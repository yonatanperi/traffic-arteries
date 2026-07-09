import { NavLink } from "react-router-dom";
import "./NavBar.css";

const LINKS = [
  { to: "/", label: "בניית ציר תנועה", end: true },
  { to: "/routes", label: "עריכת צירים" },
  { to: "/brain", label: "הצצה למוח" },
];

export default function NavBar() {
  return (
    <header className="navbar">
      <div className="navbar-inner">
        <nav className="nav-links">
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                "nav-link" + (isActive ? " nav-link--active" : "")
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  );
}
