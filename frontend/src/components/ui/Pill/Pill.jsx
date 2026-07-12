import "./Pill.css";

export default function Pill({
  as = "span",
  size = "md",
  tone = "default",
  onClick,
  className,
  children,
  ...rest
}) {
  const Tag = as;
  return (
    <Tag
      type={as === "button" ? "button" : undefined}
      className={
        `pill pill--${size} pill--${tone}` + (className ? " " + className : "")
      }
      onClick={onClick}
      {...rest}
    >
      {children}
    </Tag>
  );
}
