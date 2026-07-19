import Button from "../Button";
import { IconTrash } from "../icons";
import "./EditableGroupRow.css";

/**
 * One card in an <EditableList>: a head (badge + warnings + actions) over the
 * group's own editor.
 *
 * `actions` slots extra controls in before the remove button, and `rootRef` +
 * any extra props land on the card element itself — that's how RouteEditor
 * makes the whole card a drag handle for reordering.
 */
export default function EditableGroupRow({
  warn,
  extraClassName,
  badge,
  warning,
  actions,
  onRemove,
  removeLabel,
  removeText = "מחק",
  rootRef,
  children,
  ...rest
}) {
  return (
    <div
      ref={rootRef}
      className={
        "card route-row" +
        (warn ? " route-row--warn" : "") +
        (extraClassName ? " " + extraClassName : "")
      }
      {...rest}
    >
      <div className="route-row-head">
        {badge}
        {warning}
        <div className="route-row-actions">
          {actions}
          <Button
            variant="danger"
            className="route-remove"
            onClick={onRemove}
            aria-label={removeLabel}
            title={removeText}
          >
            <IconTrash size={15} />{" "}
            <span className="route-remove-label">{removeText}</span>
          </Button>
        </div>
      </div>
      {children}
    </div>
  );
}
