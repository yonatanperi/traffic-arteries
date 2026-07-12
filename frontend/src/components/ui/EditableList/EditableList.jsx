import Button from "../Button";
import { IconPlus } from "../icons";
import "./EditableList.css";

export default function EditableList({ children, onAdd, addLabel }) {
  return (
    <>
      <div className="editor-list">{children}</div>
      <Button variant="dashed" className="add-route-btn" onClick={onAdd}>
        <IconPlus size={16} /> {addLabel}
      </Button>
    </>
  );
}
