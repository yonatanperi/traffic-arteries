import "./IconButton.css";

export default function IconButton({
  size = "md",
  danger,
  onClick,
  ariaLabel,
  ariaPressed,
  title,
  disabled,
  className,
  children,
  ...rest
}) {
  return (
    <button
      type="button"
      className={
        `icon-btn icon-btn--${size}` +
        (danger ? " icon-btn--danger" : "") +
        (className ? " " + className : "")
      }
      onClick={onClick}
      aria-label={ariaLabel}
      aria-pressed={ariaPressed}
      title={title}
      disabled={disabled}
      {...rest}
    >
      {children}
    </button>
  );
}
