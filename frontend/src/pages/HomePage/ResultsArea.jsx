import LoaderLayout from "../../components/ui/LoaderLayout";
import EmptyState from "../../components/ui/EmptyState";
import PathResults from "../../components/home/PathResults";
import Pill from "../../components/ui/Pill";
import IdleBanner from "./IdleBanner.jsx";
import HomeStory from "./HomeStory";
import { IconAlert } from "../../components/ui/icons";
import { PLACE_TYPES } from "../../utils/placeTypes.js";
import { useIsPhone } from "../../hooks/useMediaQuery.js";

function detourMessage(destinations) {
  const list =
    destinations.length === 1
      ? destinations[0]
      : `${destinations.slice(0, -1).join(", ")} ו-${destinations[destinations.length - 1]}`;
  return destinations.length === 1
    ? `בשל ביטול זמני של היעד ${list}, נמצא ציר חלופי.`
    : `בשל ביטול זמני של היעדים ${list}, נמצאו צירים חלופיים.`;
}

export default function ResultsArea({
  loading,
  error,
  result,
  places,
  presentTypes,
  hiddenTypes,
  onToggleType,
}) {
  // Idle state only: a desktop screen fits the form and a panel that invites you
  // to use it; a phone screen doesn't, so the space below the form becomes the
  // scrollable story of what the app does (HomeStory).
  const isPhone = useIsPhone();

  return (
    <section className="results-area">
      {loading && <LoaderLayout label="מחשב צירים…" />}

      {!loading && result && result.paths.length === 0 && (
        <EmptyState
          icon={<IconAlert size={60} />}
          tone="warning"
          title="לא נמצא ציר בין הנקודות"
          message="שתי הנקודות אינן מחוברות ברשת הצירים הקיימת. נסו יעד אחר, או הוסיפו ציר מקשר בעמוד עריכת הצירים."
        />
      )}

      {!loading && result && result.paths.length > 0 && (
        <>
          {result.compromisedDetour?.length > 0 && (
            <p className="detour-notice" role="status">
              <IconAlert size={16} />
              {detourMessage(result.compromisedDetour)}
            </p>
          )}
          {presentTypes.size > 0 && (
            <div className="type-filters">
              {PLACE_TYPES.filter((t) => presentTypes.has(t.key)).map((t) => {
                const active = !hiddenTypes.has(t.key);
                return (
                  <Pill
                    as="button"
                    size="md"
                    key={t.key}
                    className={"type-filter-chip" + (active ? "" : " type-filter-chip--off")}
                    aria-pressed={active}
                    onClick={() => onToggleType(t.key)}
                  >
                    {t.label}
                  </Pill>
                );
              })}
            </div>
          )}
          <PathResults paths={result.paths} meta={result.meta} hiddenTypes={hiddenTypes} />
        </>
      )}

      {!loading && !result && !error &&
        (isPhone ? <HomeStory places={places} /> : <IdleBanner />)}
    </section>
  );
}
