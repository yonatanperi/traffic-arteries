import { useMemo, useState } from "react";
import Autocomplete from "../Autocomplete";
import { IconPlus, IconTrash, IconAlert } from "../icons";
import "../RouteEditor/RouteEditor.css";
import "../RouteChain/RouteChain.css";
import "./CompromisedEditor.css";

/**
 * Editor for compromised-destination groups: each group is a set of
 * destinations (drawn from the closed list of known destinations, no free
 * text) that are temporarily unavailable together.
 *
 * props:
 *   groups      array of arrays of destination names
 *   onChange    (nextGroups) => void
 *   suggestions the closed list of known destination names
 */
export default function CompromisedEditor({ groups, onChange, suggestions }) {
  // A destination can only belong to one group at a time.
  const usedElsewhere = useMemo(() => new Set(groups.flat()), [groups]);

  function addGroup() {
    onChange([...groups, []]);
  }
  function removeGroup(index) {
    onChange(groups.filter((_, i) => i !== index));
  }
  function updateGroup(index, nextGroup) {
    const next = groups.slice();
    next[index] = nextGroup;
    onChange(next);
  }

  return (
    <div className="editor">
      <div className="editor-list">
        {groups.map((group, i) => (
          <CompromisedGroupRow
            key={i}
            index={i}
            group={group}
            suggestions={suggestions}
            usedElsewhere={usedElsewhere}
            onChangeGroup={(next) => updateGroup(i, next)}
            onRemoveGroup={() => removeGroup(i)}
          />
        ))}
      </div>

      <button type="button" className="btn add-route-btn" onClick={addGroup}>
        <IconPlus size={16} /> הוסף קבוצה
      </button>
    </div>
  );
}

function CompromisedGroupRow({
  index,
  group,
  suggestions,
  usedElsewhere,
  onChangeGroup,
  onRemoveGroup,
}) {
  const [query, setQuery] = useState("");
  const empty = group.length === 0;

  // Offer every known destination not already claimed by *some* group (this
  // one included, since it's already shown as a pill below).
  const options = useMemo(
    () => suggestions.filter((p) => !usedElsewhere.has(p)),
    [suggestions, usedElsewhere],
  );

  function addDestination(place) {
    const p = place.trim();
    if (!p || group.includes(p)) return;
    onChangeGroup([...group, p]);
    setQuery("");
  }
  function removeDestination(place) {
    onChangeGroup(group.filter((p) => p !== place));
  }

  return (
    <div className={"route-row" + (empty ? " route-row--warn" : "")}>
      <div className="route-row-head">
        {!empty && (
          <span className="route-badge">
            {group.length === 1
              ? "יעד אחד מושבת"
              : `${group.length} יעדים מושבתים`}
          </span>
        )}
        {empty && (
          <span className="route-warn">
            <IconAlert size={14} /> קבוצה ריקה — הוסיפו יעד אחד לפחות
          </span>
        )}
        <button
          type="button"
          className="btn btn-danger route-remove"
          onClick={onRemoveGroup}
          aria-label={`מחק קבוצה ${index + 1}`}
        >
          <IconTrash size={15} /> מחק קבוצה
        </button>
      </div>

      {!empty && (
        <ol className="chain compromised-chips">
          {group.map((place) => (
            <li className="chain-item" key={place}>
              <span
                className="stop stop--compromised"
                role="button"
                tabIndex={0}
                onClick={() => removeDestination(place)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    removeDestination(place);
                  }
                }}
                aria-label={`הסר את ${place} מהקבוצה`}
                title="הסר מהקבוצה"
              >
                {place}
              </span>
            </li>
          ))}
        </ol>
      )}

      <Autocomplete
        options={options}
        value={query}
        onChange={setQuery}
        onSelect={addDestination}
        icon={<IconPlus size={16} />}
        placeholder="הוסף יעד לקבוצה…"
      />
    </div>
  );
}
