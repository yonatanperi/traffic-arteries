import { useEffect, useId, useMemo, useRef, useState } from "react";
import { IconClose } from "../icons";
import IconButton from "../IconButton";
import { fuzzyFilter } from "../../../utils/fuzzyMatch";
import "./Autocomplete.css";

/**
 * Accessible autocomplete combobox.
 *
 * props:
 *   value, onChange   controlled text value
 *   options           list of all place names, either plain strings or
 *                     `{value, label, keywords?}` objects — `keywords` are
 *                     extra terms (e.g. a place's group label, "צומת") that
 *                     widen what a query matches without appearing in the
 *                     rendered label itself. onSelect/onChange/onSubmit always
 *                     receive/set the bare `value` (or the string itself, for
 *                     plain-string options) — this component never assumes
 *                     what that value "means".
 *   label, placeholder, icon
 */
export default function Autocomplete({
  value,
  onChange,
  onSelect,
  onSubmit,
  options,
  label,
  placeholder,
  icon,
  prefix,
  invalid,
}) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const wrapRef = useRef(null);
  const listId = useId();

  const normOptions = useMemo(
    () => options.map((o) => (typeof o === "string" ? { value: o, label: o } : o)),
    [options],
  );
  const matchTextOf = (o) => [o.label, ...(o.keywords || [])].join(" ");
  const byMatchText = useMemo(
    () => new Map(normOptions.map((o) => [matchTextOf(o), o])),
    [normOptions],
  );
  const matches = useMemo(
    () =>
      fuzzyFilter(normOptions.map(matchTextOf), value, 8)
        .map((text) => byMatchText.get(text)),
    [normOptions, byMatchText, value],
  );

  // Close when clicking outside.
  useEffect(() => {
    function onDocClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  useEffect(() => setHighlight(0), [value]);

  function choose(option) {
    // When a consumer wants "pick = commit" (e.g. adding a stop), it passes
    // onSelect and we don't write the value back into the field. In that mode we
    // keep the list open so several stops can be added in a row.
    if (onSelect) {
      onSelect(option.value);
      setHighlight(0);
      setOpen(true);
    } else {
      onChange(option.value);
      setOpen(false);
    }
  }

  function onKeyDown(e) {
    if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      setOpen(true);
      return;
    }
    if (!open) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, matches.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      if (matches[highlight]) {
        e.preventDefault();
        choose(matches[highlight]);
      } else if (onSubmit && value.trim()) {
        // No matching suggestion: Enter commits the typed text (acts as "add").
        e.preventDefault();
        onSubmit(value);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  const showList = open && matches.length > 0;

  return (
    <div className={"ac" + (showList ? " ac--open" : "")} ref={wrapRef}>
      {label && <label className="ac-label">{label}</label>}
      <div
        className={
          "ac-field" +
          (showList ? " ac-field--open" : "") +
          (prefix ? " ac-field--tags" : "") +
          (invalid ? " ac-field--invalid" : "")
        }
      >
        {icon && (
          <span className="ac-icon" aria-hidden="true">
            {icon}
          </span>
        )}
        {prefix}
        <input
          className="ac-input"
          type="text"
          role="combobox"
          /* The <label> above is not associated with this input (no htmlFor),
             so name the field here rather than leaving it to the placeholder. */
          aria-label={label || placeholder}
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          autoComplete="off"
          value={value}
          placeholder={placeholder}
          onChange={(e) => {
            onChange(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {value && (
          <IconButton
            size="sm"
            className="ac-clear"
            ariaLabel="נקה"
            onClick={() => {
              onChange("");
              setOpen(true);
            }}
          >
            <IconClose size={15} />
          </IconButton>
        )}
      </div>

      {showList && (
        <ul className="ac-list" id={listId} role="listbox">
          {matches.map((option, i) => (
            <li
              key={option.value}
              role="option"
              aria-selected={i === highlight}
              className={"ac-option" + (i === highlight ? " ac-option--active" : "")}
              onMouseEnter={() => setHighlight(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(option);
              }}
            >
              <span className="ac-option-dot" aria-hidden="true" />
              {option.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
