import { NavLink } from "react-router-dom";
import "./SegmentedControl.css";

export default function SegmentedNav({
  items,
  size = "md",
  className,
  activeExtraClassName,
}) {
  return (
    <nav className={`segmented segmented--${size}` + (className ? " " + className : "")}>
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
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
