import { IconPlus } from "../icons";
import "../../styles/EditableList.css";

export default function EditableList({ children, onAdd, addLabel }) {
  return (
    <>
      <div className="editor-list">{children}</div>
      <button type="button" className="btn btn-dashed add-route-btn" onClick={onAdd}>
        <IconPlus size={16} /> {addLabel}
      </button>
    </>
  );
}
