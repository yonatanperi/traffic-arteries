import { Routes, Route, Navigate } from "react-router-dom";
import NavBar from "./components/layout/NavBar";
import HomePage from "./pages/HomePage";
import RoutesPage from "./pages/RoutesPage";
import BrainPage from "./pages/BrainPage";
import "./App.css";

export default function App() {
  return (
    <div className="app-shell">
      <NavBar />
      <main style={{ flex: 1 }}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/routes" element={<RoutesPage />} />
          <Route path="/brain" element={<BrainPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
