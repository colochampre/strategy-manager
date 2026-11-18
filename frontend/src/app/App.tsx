import { BrowserRouter } from "react-router";

import { AppRoutes } from "@/app/router";
import { useAccountDeletedStore } from "@/shared/account/account-deleted";
import { AccountDeletedScreen } from "@/shared/account/AccountDeletedScreen";

export function App() {
  // Once the account is deleted no route is mounted, so no query reads anything again (account-deletion S5).
  const deleted = useAccountDeletedStore((state) => state.deleted);
  if (deleted) return <AccountDeletedScreen />;
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
