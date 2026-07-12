import "./Page.css";

export default function Page({ className, children }) {
  return <div className={"page" + (className ? " " + className : "")}>{children}</div>;
}
