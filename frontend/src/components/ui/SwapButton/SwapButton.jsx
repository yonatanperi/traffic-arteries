import IconButton from "../IconButton/IconButton.jsx";
import { IconSwap } from "../icons";
import "./SwapButton.css";

export default function SwapButton({ onClick }) {
  return (
    <IconButton
      size="lg"
      className="swap-btn"
      onClick={onClick}
      ariaLabel="החלף מוצא ויעד"
      title="החלף מוצא ויעד"
    >
      <IconSwap size={18} />
    </IconButton>
  );
}
