import { useEffect, useId, useRef, useState } from "react";
import { IconChevron } from "../icons";
import "./Select.css";

/**
 * Accessible select — a listbox over a short, *closed* set of values.
 *
 * The sibling of Autocomplete, and deliberately built the same way (a real
 * listbox we render ourselves, not a native <select>): a native control can only
 * ever show plain text in its options, so it can't carry the dot/tone/detail that
 * the rest of this UI leans on. Reach for Autocomplete instead when the user needs
 * to *search* a long open list (e.g. places).
 *
 * props:
 *   value, onChange   controlled; onChange receives the option's own `value`
 *   options           [{ value, label, ... }] — extra fields reach `renderOption`
 *   renderOption      (option, { selected, active }) => node — custom option body;
 *                     defaults to a dot + the label
 *   renderValue       (option) => node — custom closed-state body; defaults to the label
 */
export default function Select({
  value,
  onChange,
  options,
  renderOption,
  renderValue,
  size = "md",
  className,
  ...rest
}) {
  const [open, setOpen] = useState(false);
  const selectedIndex = Math.max(
    options.findIndex((o) => o.value === value),
    0,
  );
  const [highlight, setHighlight] = useState(selectedIndex);
  const wrapRef = useRef(null);
  const listId = useId();
  const optionId = (i) => `${listId}-${i}`;

  // Close when clicking outside.
  useEffect(() => {
    function onDocClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function show() {
    setHighlight(selectedIndex); // always open onto the current value
    setOpen(true);
  }

  function choose(option) {
    onChange(option.value);
    setOpen(false);
  }

  function onKeyDown(e) {
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter") {
        e.preventDefault();
        show();
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, options.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (options[highlight]) choose(options[highlight]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  }

  const selected = options[selectedIndex];

  return (
    <div
      className={
        "sel sel--" + size + (open ? " sel--open" : "") + (className ? " " + className : "")
      }
      ref={wrapRef}
    >
      <button
        type="button"
        className={"sel-field" + (open ? " sel-field--open" : "")}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={listId}
        aria-activedescendant={open ? optionId(highlight) : undefined}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={onKeyDown}
        {...rest}
      >
        <span className="sel-value">
          {renderValue ? renderValue(selected) : selected?.label}
        </span>
        <IconChevron size={13} className="sel-chevron" />
      </button>

      {open && (
        <ul className="sel-list" id={listId} role="listbox">
          {options.map((option, i) => {
            const isSelected = option.value === value;
            const isActive = i === highlight;
            return (
              <li
                key={String(option.value)}
                id={optionId(i)}
                role="option"
                aria-selected={isSelected}
                className={
                  "sel-option" +
                  (isActive ? " sel-option--active" : "") +
                  (isSelected ? " sel-option--selected" : "")
                }
                onMouseEnter={() => setHighlight(i)}
                onMouseDown={(e) => {
                  e.preventDefault(); // keep focus on the button; don't start a drag
                  choose(option);
                }}
              >
                {renderOption ? (
                  renderOption(option, { selected: isSelected, active: isActive })
                ) : (
                  <>
                    <span className="sel-option-dot" aria-hidden="true" />
                    {option.label}
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
