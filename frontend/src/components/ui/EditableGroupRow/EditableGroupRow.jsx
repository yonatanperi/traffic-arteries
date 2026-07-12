import Button from "../Button";
import { IconTrash } from "../icons";
import "./EditableGroupRow.css";

export default function EditableGroupRow({
  warn,
  extraClassName,
  badge,
  warning,
  onRemove,
  removeLabel,
  removeText = "מחק",
  children,
}) {
  return (
    <div
      className={
        "card route-row" +
        (warn ? " route-row--warn" : "") +
        (extraClassName ? " " + extraClassName : "")
      }
    >
      <div className="route-row-head">
        {badge}
        {warning}
        <Button
          variant="danger"
          className="route-remove"
          onClick={onRemove}
          aria-label={removeLabel}
        >
          <IconTrash size={15} /> {removeText}
        </Button>
      </div>
      {children}
    </div>
  );
}
