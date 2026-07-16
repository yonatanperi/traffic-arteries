import { Routes, Route, Navigate } from "react-router-dom";
import NavBar from "./components/layout/NavBar";
import ServerGate from "./components/layout/ServerGate";
import HomePage from "./pages/HomePage";
import RoutesPage from "./pages/RoutesPage";
import BrainPage from "./pages/BrainPage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import UserManagementPage from "./pages/UserManagementPage";
import { ProtectedRoute } from "./components/auth";
import "./App.css";

export default function App() {
  return (
    <div className="app-shell">
      <NavBar />
      <main style={{ flex: 1 }}>
        <ServerGate>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/routes"
            element={
              <ProtectedRoute roles={["editor", "admin"]}>
                <RoutesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/brain"
            element={
              <ProtectedRoute roles={["editor", "admin"]}>
                <BrainPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/users"
            element={
              <ProtectedRoute roles={["editor", "admin"]}>
                <UserManagementPage />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </ServerGate>
      </main>
    </div>
  );
}
