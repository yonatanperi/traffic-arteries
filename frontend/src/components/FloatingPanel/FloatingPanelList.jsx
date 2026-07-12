export function FloatingPanelList({ children }) {
  return <ul className="fp-list">{children}</ul>;
}

export function FloatingPanelListItem({ onClick, warn, meta, children }) {
  return (
    <li>
      <button type="button" className="fp-list-btn" onClick={onClick}>
        <span className={"fp-dot" + (warn ? " fp-dot--warn" : "")} aria-hidden="true" />
        {children}
        {meta != null && <span className="fp-list-meta">{meta}</span>}
      </button>
    </li>
  );
}
