import { useMemo, useState } from "react";
import Autocomplete from "../../ui/Autocomplete";
import RemovableChip from "../../ui/RemovableChip";
import Pill from "../../ui/Pill";
import EditableList from "../../ui/EditableList";
import EditableGroupRow from "../../ui/EditableGroupRow";
import { IconPlus, IconAlert } from "../../ui/icons";
import "../../shared/RouteChain/RouteChain.css";
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
      <EditableList onAdd={addGroup} addLabel="הוסף קבוצה">
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
      </EditableList>
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
    <EditableGroupRow
      warn={empty}
      badge={
        !empty && (
          <Pill size="sm" className="route-badge">
            {group.length === 1
              ? "יעד אחד מושבת"
              : `${group.length} יעדים מושבתים`}
          </Pill>
        )
      }
      warning={
        empty && (
          <span className="route-warn">
            <IconAlert size={14} /> קבוצה ריקה — הוסיפו יעד אחד לפחות
          </span>
        )
      }
      onRemove={onRemoveGroup}
      removeLabel={`מחק קבוצה ${index + 1}`}
      removeText="מחק קבוצה"
    >
      {!empty && (
        <ol className="chain compromised-chips">
          {group.map((place) => (
            <li className="chain-item" key={place}>
              <RemovableChip
                className="stop stop--compromised"
                onRemove={() => removeDestination(place)}
                ariaLabel={`הסר את ${place} מהקבוצה`}
                title="הסר מהקבוצה"
              >
                {place}
              </RemovableChip>
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
    </EditableGroupRow>
  );
}
