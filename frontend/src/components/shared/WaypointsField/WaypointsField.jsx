import Autocomplete from "../../ui/Autocomplete";
import IconButton from "../../ui/IconButton";
import Button from "../../ui/Button";
import { IconRoute, IconPlus, IconClose } from "../../ui/icons";
import "./WaypointsField.css";

/**
 * Required-intermediate-stop editor: a list of autocomplete rows (each
 * removable) plus an "add stop" affordance. Shared by every path-search form
 * (home search, brain toolbar's path mode) that reads/writes the `via` URL
 * param via `useWaypoints`.
 */
export default function WaypointsField({
  places,
  vias,
  onAddVia,
  onSetVia,
  onRemoveVia,
  invalidPlaces,
}) {
  return (
    <div className="waypoints">
      {vias.length > 0 && (
        <div className="waypoints-head">
          <span className="waypoints-title">
            <IconRoute size={15} />
            עצירות ביניים
          </span>
          <span className="waypoints-hint">
            הציר יעבור בכל העצירות, בסדר האופטימלי
          </span>
        </div>
      )}

      {vias.map((v, i) => (
        <div className="waypoint-row" key={i}>
          <Autocomplete
            icon={<IconRoute size={16} />}
            placeholder="תחנה שהציר חייב לעבור בה"
            options={places}
            value={v}
            onChange={(val) => onSetVia(i, val)}
            invalid={invalidPlaces?.has(v.trim())}
          />
          <IconButton
            size="lg"
            className="waypoint-remove"
            onClick={() => onRemoveVia(i)}
            ariaLabel="הסר עצירה"
            title="הסר עצירה"
          >
            <IconClose size={16} />
          </IconButton>
        </div>
      ))}

      <Button variant="dashed" className="waypoint-add" onClick={onAddVia}>
        <IconPlus size={16} />
        הוסף עצירת ביניים
      </Button>
    </div>
  );
}
