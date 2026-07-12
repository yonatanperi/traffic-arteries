import { NavLink, useLocation } from "react-router-dom";
import "./SegmentedControl.css";

export default function SegmentedNav({
  items,
  size = "md",
  className,
  activeExtraClassName,
}) {
  const location = useLocation();

  return (
    <nav className={`segmented segmented--${size}` + (className ? " " + className : "")}>
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={{ pathname: item.to, search: location.search }}
          end={item.end}
          className={({ isActive }) =>
            "segmented-item" +
            (isActive
              ? " segmented-item--on" +
                (activeExtraClassName ? " " + activeExtraClassName : "")
              : "")
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
