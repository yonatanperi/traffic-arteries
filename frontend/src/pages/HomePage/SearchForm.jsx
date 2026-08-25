import { useMemo } from "react";
import Autocomplete from "../../components/ui/Autocomplete";
import SwapButton from "../../components/ui/SwapButton";
import Button from "../../components/ui/Button";
import WaypointsField from "../../components/shared/WaypointsField";
import { IconOrigin, IconDestination, IconSearch } from "../../components/ui/icons";
import { classifyPlace, groupLabel } from "../../utils/placeGroups.js";

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
  // Each place's group is derived from its own prefix, purely for a searchable
  // `keywords` term (e.g. typing "צומת" surfaces every junction) — the group
  // is never a separate field on the wire.
  const options = useMemo(
    () => places.map((p) => ({ value: p, label: p, keywords: [groupLabel(classifyPlace(p))] })),
    [places],
  );

  return (
    <form className="search-panel card" onSubmit={onSubmit}>
      <div className="search-fields">
        <Autocomplete
          label="מוצא"
          icon={<IconOrigin size={17} />}
          placeholder="מקום המוצא"
          options={options}
          value={start}
          onChange={onStartChange}
          invalid={invalidPlaces?.has(start.trim())}
        />

        <SwapButton onClick={onSwap} />

        <Autocomplete
          label="יעד"
          icon={<IconDestination size={17} />}
          placeholder="מקום היעד"
          options={options}
          value={end}
          onChange={onEndChange}
          invalid={invalidPlaces?.has(end.trim())}
        />
      </div>

      <WaypointsField
        places={options}
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
