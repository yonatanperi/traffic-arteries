import { useEffect } from "react";
import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
import SearchForm from "./SearchForm.jsx";
import TripBar from "./TripBar.jsx";
import ResultsArea from "./ResultsArea.jsx";
import { useRouteSearch } from "./useRouteSearch.js";
import { useIsPhone } from "../../hooks/useMediaQuery.js";
import "./HomePage.css";

export default function HomePage() {
  const search = useRouteSearch();
  // On a phone the form is a screenful, so once there are results it folds into
  // the trip bar and hands the viewport to them. Desktop has room for both and
  // always renders the form — this is the only branch that differs.
  const isPhone = useIsPhone();
  const folded = isPhone && search.didSearch;

  // Folding removes everything above the results and unfolding puts the form
  // back there, so either way the page has to start from the top.
  useEffect(() => {
    if (isPhone) window.scrollTo({ top: 0 });
  }, [folded, isPhone]);

  function handleSubmit(e) {
    e.preventDefault();
    search.submit();
  }

  return (
    <Page className="page--home">
      {folded ? (
        <TripBar
          start={search.start}
          end={search.end}
          vias={search.vias}
          onEdit={search.reopenSearch}
        />
      ) : (
        <>
          <PageHeader
            title="לאן ניסע היום?"
            subtitle="בחרו נקודת מוצא ויעד, נבנה את ציר התנועה עבורכם."
          />

          <SearchForm
            places={search.places}
            start={search.start}
            onStartChange={search.setStart}
            end={search.end}
            onEndChange={search.setEnd}
            onSwap={search.swap}
            vias={search.vias}
            onAddVia={search.addVia}
            onSetVia={search.setVia}
            onRemoveVia={search.removeVia}
            invalidPlaces={search.invalidPlaces}
            loading={search.loading}
            onSubmit={handleSubmit}
          />
        </>
      )}

      {search.error && (
        <p className="form-error" role="alert">
          {search.error}
        </p>
      )}

      <ResultsArea
        loading={search.loading}
        error={search.error}
        result={search.result}
        places={search.places}
        presentTypes={search.presentTypes}
        hiddenTypes={search.hiddenTypes}
        onToggleType={search.toggleType}
      />
    </Page>
  );
}
