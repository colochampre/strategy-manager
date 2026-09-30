import { Route, Routes } from "react-router";

import { OverviewPage } from "@/features/overview/OverviewPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { StrategiesPage } from "@/features/strategies/StrategiesPage";
import { StrategyDetailPage } from "@/features/strategies/StrategyDetailPage";
import { AppShell } from "@/shared/layout/AppShell";
import { NotFoundPage } from "@/shared/layout/NotFoundPage";

/**
 * The route map (design.md § 15). Every route lives inside the shell, the
 * client-side not-found included. The caller supplies the router: a
 * `BrowserRouter` in `App`, a `MemoryRouter` in tests.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
