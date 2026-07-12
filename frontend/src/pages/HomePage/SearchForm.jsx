import Autocomplete from "../../components/ui/Autocomplete";
import SwapButton from "../../components/ui/SwapButton";
import IconButton from "../../components/ui/IconButton";
import {
  IconOrigin,
  IconDestination,
  IconRoute,
  IconPlus,
  IconClose,
  IconSearch,
} from "../../components/ui/icons";

export default function SearchForm({
  places,
  start,
  onStartChange,
  end,
  onEndChange,
  onSwap,
  vias,
  onAddVia,
  onSetVia,
  onRemoveVia,
  loading,
  onSubmit,
}) {
  return (
    <form className="search-panel card" onSubmit={onSubmit}>
      <div className="search-fields">
        <Autocomplete
          label="מוצא"
          icon={<IconOrigin size={17} />}
          placeholder="מקום המוצא"
          options={places}
          value={start}
          onChange={onStartChange}
        />

        <SwapButton onClick={onSwap} />

        <Autocomplete
          label="יעד"
          icon={<IconDestination size={17} />}
          placeholder="מקום היעד"
          options={places}
          value={end}
          onChange={onEndChange}
        />
      </div>

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

        <button type="button" className="btn btn-dashed waypoint-add" onClick={onAddVia}>
          <IconPlus size={16} />
          הוסף עצירת ביניים
        </button>
      </div>

      <button type="submit" className="btn btn-primary search-submit" disabled={loading}>
        <IconSearch size={18} />
        {loading ? "מחפש…" : "בניית ציר תנועה"}
      </button>
    </form>
  );
}
