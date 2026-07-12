import { forwardRef } from "react";
import "./Button.css";

/**
 * `as` lets the same visual button render as a router NavLink/Link when the
 * action navigates instead of handling a click (e.g. NavBar's auth links).
 */
const Button = forwardRef(function Button(
  {
    as = "button",
    variant = "default",
    size = "md",
    type = "button",
    className,
    children,
    ...rest
  },
  ref,
) {
  const Tag = as;
  return (
    <Tag
      ref={ref}
      type={as === "button" ? type : undefined}
      className={
        "btn" +
        (variant !== "default" ? ` btn-${variant}` : "") +
        (size !== "md" ? ` btn--${size}` : "") +
        (className ? " " + className : "")
      }
      {...rest}
    >
      {children}
    </Tag>
  );
});

export default Button;
