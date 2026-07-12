import { SegmentedNav } from "../../ui/SegmentedControl";
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
        <SegmentedNav items={LINKS} activeExtraClassName="nav-link--active" />
      </div>
    </header>
  );
}
