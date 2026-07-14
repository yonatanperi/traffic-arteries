import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import Button from "../Button";
import { IconPlus } from "../icons";
import "./EditableList.css";

/**
 * The list + its "add" button. Adding always ends with a smooth scroll down to
 * the freshly added row, and once the inline add button has scrolled out of
 * view a floating twin of it takes over at the bottom of the screen — so the
 * action stays reachable from anywhere in a long list.
 */
export default function EditableList({ children, onAdd, addLabel }) {
  const addRef = useRef(null);
  const [addInView, setAddInView] = useState(true);
  const [scrollPending, setScrollPending] = useState(false);

  useEffect(() => {
    const el = addRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) =>
      setAddInView(entry.isIntersecting),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Scroll only after the new row has rendered: the page has grown to its full
  // height by then, so the scroll lands on the new row rather than short of it.
  useEffect(() => {
    if (!scrollPending) return;
    setScrollPending(false);
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: "smooth",
    });
  }, [children, scrollPending]);

  function handleAdd() {
    onAdd();
    setScrollPending(true);
  }

  return (
    <>
      <div className="editor-list">{children}</div>
      <Button
        ref={addRef}
        variant="dashed"
        className="add-route-btn"
        onClick={handleAdd}
      >
        <IconPlus size={16} /> {addLabel}
      </Button>

      {createPortal(
        <AnimatePresence>
          {!addInView && (
            <motion.div
              className="add-route-float"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 16 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            >
              <Button variant="primary" onClick={handleAdd}>
                <IconPlus size={16} /> {addLabel}
              </Button>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
