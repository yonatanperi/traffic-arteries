import "./EmptyState.css";

export default function EmptyState({ icon, title, message, tone = "neutral" }) {
  return (
    <div className={"empty-state empty-state--" + tone}>
      {icon && (
        <div className="empty-state-icon" aria-hidden="true">
          {icon}
        </div>
      )}
      <h3 className="empty-state-title">{title}</h3>
      {message && <p className="empty-state-message">{message}</p>}
    </div>
  );
}
