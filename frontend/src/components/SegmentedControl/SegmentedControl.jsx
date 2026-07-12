import "./SegmentedControl.css";

export default function SegmentedControl({
  items,
  value,
  onChange,
  size = "md",
  ariaLabel,
  className,
}) {
  return (
    <div
      className={`segmented segmented--${size}` + (className ? " " + className : "")}
      role="tablist"
      aria-label={ariaLabel}
    >
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          role="tab"
          aria-selected={item.value === value}
          className={
            "segmented-item" + (item.value === value ? " segmented-item--on" : "")
          }
          onClick={() => onChange(item.value)}
        >
          {item.icon}
          {item.label}
        </button>
      ))}
    </div>
  );
}
