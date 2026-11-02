import { Outlet } from "react-router";

import { useMe } from "@/shared/api/me";
import { NotFoundPage } from "@/shared/layout/NotFoundPage";

/**
 * The pages only the admin has (AD11). The server refuses their reads anyway; this is so that anyone else meets
 * "not found" and not a page of refusals. Nothing is drawn until the answer is known, so a stranger never sees a
 * page's frame and the admin never sees "not found".
 */
export function AdminRoute() {
  const me = useMe();

  if (me.data?.isAdmin === true) return <Outlet />;
  if (me.isPending) return null;
  return <NotFoundPage />;
}
