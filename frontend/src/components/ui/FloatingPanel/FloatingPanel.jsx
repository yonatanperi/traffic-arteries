import IconButton from "../IconButton";
import { IconClose } from "../icons";
import "./FloatingPanel.css";

export default function FloatingPanel({ side, icon, title, onClose, ariaLabel, children }) {
  return (
    <div className={`card fp fp--${side}`} role="dialog" aria-label={ariaLabel}>
      <header className="fp-head">
        <div className="fp-title-wrap">
          {icon}
          <h3 className="fp-title">{title}</h3>
        </div>
        <IconButton size="md" className="fp-close" onClick={onClose} ariaLabel="סגור">
          <IconClose size={16} />
        </IconButton>
      </header>
      {children}
    </div>
  );
}
