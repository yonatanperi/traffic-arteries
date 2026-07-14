import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
import SearchForm from "./SearchForm.jsx";
import ResultsArea from "./ResultsArea.jsx";
import { useRouteSearch } from "./useRouteSearch.js";
import "./HomePage.css";

export default function HomePage() {
  const search = useRouteSearch();

  function handleSubmit(e) {
    e.preventDefault();
    search.submit();
  }

  return (
    <Page>
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

      {search.error && (
        <p className="form-error" role="alert">
          {search.error}
        </p>
      )}

      <ResultsArea
        loading={search.loading}
        error={search.error}
        result={search.result}
        presentTypes={search.presentTypes}
        hiddenTypes={search.hiddenTypes}
        onToggleType={search.toggleType}
      />
    </Page>
  );
}
