import Autocomplete from "../../components/ui/Autocomplete";
import SwapButton from "../../components/ui/SwapButton";
import Button from "../../components/ui/Button";
import WaypointsField from "../../components/shared/WaypointsField";
import { IconOrigin, IconDestination, IconSearch } from "../../components/ui/icons";

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
  invalidPlaces,
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
          invalid={invalidPlaces?.has(start.trim())}
        />

        <SwapButton onClick={onSwap} />

        <Autocomplete
          label="יעד"
          icon={<IconDestination size={17} />}
          placeholder="מקום היעד"
          options={places}
          value={end}
          onChange={onEndChange}
          invalid={invalidPlaces?.has(end.trim())}
        />
      </div>

      <WaypointsField
        places={places}
        vias={vias}
        onAddVia={onAddVia}
        onSetVia={onSetVia}
        onRemoveVia={onRemoveVia}
        invalidPlaces={invalidPlaces}
      />

      <Button
        type="submit"
        variant="primary"
        className="search-submit"
        disabled={loading}
      >
        <IconSearch size={18} />
        {loading ? "מחפש…" : "בניית ציר תנועה"}
      </Button>
    </form>
  );
}
