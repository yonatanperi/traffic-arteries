import { useEffect, useRef } from "react";
import "./ConfirmModal.css";

/**
 * Minimal centered confirmation dialog.
 *
 * props:
 *   title, message           strings
 *   confirmLabel, cancelLabel button text
 *   onConfirm, onCancel      handlers (Escape / backdrop click = cancel)
 */
export default function ConfirmModal({
  title,
  message,
  confirmLabel = "אישור",
  cancelLabel = "ביטול",
  onConfirm,
  onCancel,
}) {
  const confirmRef = useRef(null);

  useEffect(() => {
    confirmRef.current?.focus();
    function onKey(e) {
      if (e.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="confirm-overlay" onMouseDown={onCancel}>
      <div
        className="confirm-modal"
        role="dialog"
        aria-modal="true"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {title && <h3 className="confirm-title">{title}</h3>}
        {message && <p className="confirm-message">{message}</p>}
        <div className="confirm-actions">
          <button type="button" className="btn confirm-cancel" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            type="button"
            ref={confirmRef}
            className="btn btn-primary"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
