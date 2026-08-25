import { useMemo } from "react";
import CountUp from "./CountUp.jsx";
import { useReveal } from "./useReveal.js";
import {
  ScanVisual,
  ConcentrationVisual,
  PriorityVisual,
  MatchVisual,
  ResultsVisual,
} from "./visuals.jsx";
import { PLACE_GROUPS, classifyPlace } from "../../../utils/placeGroups.js";
import Button from "../../../components/ui/Button";
import { IconSearch } from "../../../components/ui/icons";
import "./HomeStory.css";

/**
 * The phone home page below the search form: what the app does, told as a
 * scroll.
 *
 * Desktop keeps the compact <IdleBanner> panel — it has the room to show the
 * form and its invitation at once. A phone doesn't, so instead of a single
 * panel sized to the leftover, the space under the form becomes the story: one
 * idea per screen, each one illustrated by the thing the router actually does.
 *
 * Every section reveals once (useReveal) and the illustrations animate on that
 * reveal, so nothing moves until it is looked at.
 */

function Section({ eyebrow, title, body, tone, eager, children }) {
  const [ref, shown] = useReveal({ eager });
  return (
    <section
      ref={ref}
      className={
        "story-section" +
        (tone ? " story-section--" + tone : "") +
        (shown ? " is-in" : "")
      }
    >
      <p className="story-eyebrow">{eyebrow}</p>
      <h2 className="story-title">{title}</h2>
      <p className="story-body">{body}</p>
      {children && (
        <div className="story-visual">
          {typeof children === "function" ? children(shown) : children}
        </div>
      )}
    </section>
  );
}

/** Scrolls back to the form and opens it for input. */
function goToSearch() {
  window.scrollTo({ top: 0, behavior: "smooth" });
  // The form is above this component, not inside it, and it is the same one
  // control on every phone screen — a query beats threading a ref up through
  // HomePage just to hand it back down.
  const field = document.querySelector(".search-fields .ac-input");
  if (field) field.focus({ preventScroll: true });
}

export default function HomeStory({ places }) {
  // The one live number on this page: every other figure below states how the
  // router behaves, this one states what it is currently searching.
  const counts = useMemo(() => {
    const byType = new Map(PLACE_GROUPS.map((t) => [t.key, 0]));
    places.forEach((place) => {
      const type = classifyPlace(place);
      byType.set(type, byType.get(type) + 1);
    });
    return PLACE_GROUPS.filter((t) => byType.get(t.key) > 0).map((t) => ({
      key: t.key,
      label: t.label,
      value: byType.get(t.key),
    }));
  }, [places]);

  return (
    <div className="home-story">
      <Section
        eager
        eyebrow="האלגוריתם"
        title={
          <>
            סורק כל ציר אפשרי.
            <br />
            מחזיר את הטובים ביותר.
          </>
        }
        body="בכל חיפוש נבנים עשרות צירים מועמדים בין שתי הנקודות. כל אחד מהם נבחן במלואו מול רשת הצירים המאושרת — ורק המובילים מגיעים אליכם."
      >
        <ScanVisual />
      </Section>

      {places.length > 0 && (
        <Section
          eyebrow="הרשת"
          title="כל הרשת. בכל חיפוש."
          body="הצירים שאתם מזינים הם המפה שעליה נבנה כל ציר — ואלה המקומות שעליהם היא פרושה כרגע."
          tone="alt"
        >
          {(shown) => (
            <div className="stats">
              <div className="stat stat--lead">
                <span className="stat-num">
                  <CountUp value={places.length} run={shown} />
                </span>
                <span className="stat-label">מקומות ברשת</span>
              </div>
              <div className="stat-row">
                {counts.map((c) => (
                  <div className="stat" key={c.key}>
                    <span className="stat-num">
                      <CountUp value={c.value} run={shown} />
                    </span>
                    <span className="stat-label">{c.label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Section>
      )}

      <Section
        eyebrow="דירוג"
        title="לא הדרך הקצרה. הדרך הנכונה."
        body="ציר שמורכב משלושה תת-מסלולים שונים הוא שני מעברים בדרך. ציר אחד רציף מנצח אותו — גם כשהוא ארוך במעט."
      >
        <ConcentrationVisual />
      </Section>

      <Section
        eyebrow="עדיפות"
        title="עדיפות לפני הכול."
        body="ציר שנאלץ לרכוב על תת-מסלול בעדיפות נמוכה יורד בדירוג, ולכן לפעמים דווקא הציר הארוך יותר הוא זה שמוצג ראשון."
        tone="alt"
      >
        <PriorityVisual />
      </Section>

      <Section
        eyebrow="שקיפות"
        title="ציון לכל ציר."
        body="כל תוצאה מגיעה עם אחוז התאמה ועם תת המסלולים שמהם היא מורכבת — כדי שתדעו בדיוק על מה אתם נוסעים."
      >
        {(shown) => <MatchVisual run={shown} />}
      </Section>

      <Section
        eyebrow="תוצאות"
        title="שלוש אפשרויות בכל חיפוש."
        body="כל חיפוש מחזיר את שלושת הצירים הטובים ביותר, כולל חלופות בעדיפות שונה — ולא תשובה יחידה שאין מה להשוות אליה."
        tone="alt"
      >
        <ResultsVisual />
      </Section>

      <section className="story-cta">
        <h2 className="story-title">מוכנים לצאת לדרך?</h2>
        <Button
          variant="primary"
          className="story-cta-btn"
          onClick={goToSearch}
        >
          <IconSearch size={18} />
          בניית ציר תנועה
        </Button>
      </section>
    </div>
  );
}
