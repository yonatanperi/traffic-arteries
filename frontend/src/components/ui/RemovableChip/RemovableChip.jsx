export default function RemovableChip({ onRemove, ariaLabel, title, className, children }) {
  return (
    <span
      role="button"
      tabIndex={0}
      className={className}
      onClick={onRemove}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onRemove();
        }
      }}
      aria-label={ariaLabel}
      title={title}
    >
      {children}
    </span>
  );
}
