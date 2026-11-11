import { Navigate, Route, Routes } from "react-router-dom";
import { Loading } from "../components/States";
import { useAuth } from "../lib/auth";
import Analytics from "./Analytics";
import Approvals from "./Approvals";
import Inbox from "./Inbox";
import JobDetailPage from "./JobDetail";
import Messages from "./Messages";
import Onboarding from "./Onboarding";
import Pipeline from "./Pipeline";
import RunViewer from "./RunViewer";
import Runs from "./Runs";
import SettingsPage from "./Settings";
import { Shell } from "./Shell";
import SignIn from "./SignIn";
import Studio from "./Studio";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="page"><Loading label="Checking your session" /></div>;
  if (!user) return <Navigate to="/sign-in" replace />;
  if (!user.onboarded) return <Navigate to="/onboarding" replace />;
  return <>{children}</>;
}

function RequireUser({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="page"><Loading label="Checking your session" /></div>;
  if (!user) return <Navigate to="/sign-in" replace />;
  return <>{children}</>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignIn />} />
      <Route
        path="/onboarding"
        element={
          <RequireUser>
            <Onboarding />
          </RequireUser>
        }
      />
      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route index element={<Inbox />} />
        <Route path="jobs/:id" element={<JobDetailPage />} />
        <Route path="studio/:id" element={<Studio />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="pipeline" element={<Pipeline />} />
        <Route path="messages" element={<Messages />} />
        <Route path="messages/:threadId" element={<Messages />} />
        <Route path="runs" element={<Runs />} />
        <Route path="runs/:id" element={<RunViewer />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
