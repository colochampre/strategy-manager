import { Activity, ChevronDown, LogOut, PanelLeftClose, PanelLeftOpen, User, X } from "lucide-react";
import { type ReactNode, type Ref, useState } from "react";
import { useTranslation } from "react-i18next";
import { matchPath, NavLink, useLocation } from "react-router";

import { ACCESS_LOGOUT } from "@/shared/account/AccountDeletedScreen";
import { useMe } from "@/shared/api/me";
import { cn } from "@/shared/lib/cn";
import { NavBadge } from "@/shared/layout/NavBadge";
import { type NavGroup, type NavLeaf, type NavLinkItem, useNavigation } from "@/shared/layout/navItems";
import { useSidebarStore } from "@/shared/layout/sidebar-store";
import { useBuildTag } from "@/shared/layout/useBuildTag";

/** One row of the sidebar, as the prototype draws it: 40 px high, the icon at 16 px. */
const ROW =
  "relative flex h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-sm transition-colors hover:bg-panel-2 hover:text-ink motion-reduce:transition-none";
const ROW_COLLAPSED = "justify-center px-0";

interface BodyProps {
  /** Icons only. The drawer is never collapsed. */
  collapsed: boolean;
  /** Called when a link is followed: the drawer closes on it. */
  onNavigate?: (() => void) | undefined;
  /** What sits right of the brand: the collapse button on the desktop, the close button in the drawer. */
  control: ReactNode;
}

function Label({ collapsed, children }: { collapsed: boolean; children: ReactNode }) {
  // Collapsed, the name stays for assistive technology and for the link's own name.
  return <span className={cn("min-w-0 flex-1 truncate", collapsed && "sr-only")}>{children}</span>;
}

function Leaf({ item, collapsed, onNavigate }: { item: NavLeaf } & Pick<BodyProps, "collapsed" | "onNavigate">) {
  const { t } = useTranslation();
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(ROW, collapsed && ROW_COLLAPSED, isActive ? "bg-panel-2 text-ink" : "text-ink-2")
      }
    >
      {({ isActive }) => (
        <>
          <item.icon aria-hidden="true" className={cn("size-4 shrink-0", isActive && "text-gain")} />
          <Label collapsed={collapsed}>{t(`nav.${item.labelKey}`)}</Label>
        </>
      )}
    </NavLink>
  );
}

function SubLink({ item, onNavigate }: { item: NavLinkItem; onNavigate?: (() => void) | undefined }) {
  const { t } = useTranslation();
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "relative flex h-8.5 items-center justify-between gap-2 pl-5.5 pr-3 text-[13.5px] transition-colors hover:bg-panel-2 hover:text-ink motion-reduce:transition-none",
          isActive
            ? "rounded-r-lg bg-panel-2 text-ink before:absolute before:inset-y-1.5 before:-left-px before:w-0.5 before:bg-gain"
            : "rounded-lg text-ink-2",
        )
      }
    >
      <span className="truncate">{t(`nav.${item.labelKey}`)}</span>
      {item.badge && <NavBadge />}
    </NavLink>
  );
}

/**
 * A button that opens its pages below it. Its chevron turns and the list grows with the height of its content, both
 * at 200 ms and instant under `prefers-reduced-motion`. While the sidebar is collapsed to icons there is no room for
 * a list, so pressing the button opens the sidebar first: the pages stay reachable.
 */
function Group({
  group,
  collapsed,
  onNavigate,
  onExpandSidebar,
}: { group: NavGroup; onExpandSidebar: () => void } & Pick<BodyProps, "collapsed" | "onNavigate">) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const inside = group.children.some((child) => matchPath({ path: child.to, end: false }, pathname) !== null);
  const [open, setOpen] = useState(group.openByDefault || inside);
  const shown = open && !collapsed;

  const press = () => {
    if (collapsed) {
      onExpandSidebar();
      setOpen(true);
      return;
    }
    setOpen(!open);
  };

  return (
    <div>
      <button
        type="button"
        aria-expanded={shown}
        onClick={press}
        className={cn(ROW, collapsed && ROW_COLLAPSED, inside ? "text-ink" : "text-ink-2")}
      >
        <group.icon aria-hidden="true" className={cn("size-4 shrink-0", inside && "text-gain")} />
        <Label collapsed={collapsed}>{t(`nav.${group.labelKey}`)}</Label>
        {/* What needs the owner stays in view while the list that holds it is closed. */}
        {!shown && group.children.some((child) => child.badge) && <NavBadge corner={collapsed} />}
        {!collapsed && (
          <ChevronDown
            aria-hidden="true"
            className={cn(
              "size-4 shrink-0 text-ink-3 transition-transform duration-200 ease-out motion-reduce:transition-none",
              shown && "rotate-180",
            )}
          />
        )}
      </button>
      <div
        data-group-panel
        aria-hidden={!shown}
        inert={!shown}
        className={cn(
          "grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none",
          shown ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="overflow-hidden">
          <div className="mb-1 ml-5 mt-0.5 flex flex-col border-l border-rule">
            {group.children.map((child) => (
              <SubLink key={child.to} item={child} onNavigate={onNavigate} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function BuildTag({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const tag = useBuildTag();
  if (tag === null) return null;
  return (
    <p
      data-testid="build-tag"
      className={cn("mt-2 px-3 pt-1.5 font-mono text-[11.5px] text-ink-3", collapsed && "px-0 text-center text-[10px]")}
    >
      <span className={cn(collapsed && "sr-only")}>{t("nav.build")} </span>
      <span>{tag}</span>
    </p>
  );
}

/** The brand, the pages, and at the foot the account, the way out and the build. One body for the sidebar and the drawer. */
function SidebarBody({ collapsed, onNavigate, control }: BodyProps) {
  const { t } = useTranslation();
  const me = useMe().data;
  const { main, admin } = useNavigation();
  const setCollapsed = useSidebarStore((state) => state.setCollapsed);
  const expandSidebar = () => setCollapsed(false);
  const signedInAs = me?.displayName ?? me?.email;

  return (
    <>
      <div className={cn("flex items-center justify-between pb-5 pl-1.5 pr-1", collapsed && "flex-col gap-3 px-0 pb-4.5")}>
        <div className="flex items-center gap-2.5">
          <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-lg bg-gain text-ground">
            <Activity aria-hidden="true" className="size-4.5" />
          </span>
          <span className={cn("font-display text-[15px] font-semibold tracking-[0.01em] text-ink", collapsed && "sr-only")}>
            {t("app.name")}
          </span>
        </div>
        {control}
      </div>
      <div className="flex flex-col gap-0.5">
        {main.map((entry) =>
          "children" in entry ? (
            <Group
              key={entry.id}
              group={entry}
              collapsed={collapsed}
              onNavigate={onNavigate}
              onExpandSidebar={expandSidebar}
            />
          ) : (
            <Leaf key={entry.to} item={entry} collapsed={collapsed} onNavigate={onNavigate} />
          ),
        )}
      </div>
      <div className="mt-auto flex flex-col gap-0.5 border-t border-rule pt-3">
        {admin !== null && (
          <Group group={admin} collapsed={collapsed} onNavigate={onNavigate} onExpandSidebar={expandSidebar} />
        )}
        <NavLink
          to="/settings"
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(ROW, "h-auto min-h-10 py-1.5", collapsed && ROW_COLLAPSED, isActive ? "bg-panel-2 text-ink" : "text-ink-2")
          }
        >
          {({ isActive }) => (
            <>
              <User aria-hidden="true" className={cn("size-4 shrink-0", isActive && "text-gain")} />
              <span className={cn("flex min-w-0 flex-1 flex-col leading-tight", collapsed && "sr-only")}>
                <span className="truncate font-medium text-ink">{t("nav.account")}</span>
                {signedInAs !== undefined && <span className="truncate text-xs text-ink-3">{signedInAs}</span>}
              </span>
            </>
          )}
        </NavLink>
        <a href={ACCESS_LOGOUT} className={cn(ROW, collapsed && ROW_COLLAPSED, "text-ink-2")}>
          <LogOut aria-hidden="true" className="size-4 shrink-0" />
          <Label collapsed={collapsed}>{t("nav.signOut")}</Label>
        </a>
        <BuildTag collapsed={collapsed} />
      </div>
    </>
  );
}

/**
 * The left rail from `lg`, 248 px wide or 72 px collapsed to icons (kept in the browser). Its width changes
 * gradually, and at once under `prefers-reduced-motion`. Below `lg` the drawer takes its place.
 */
export function Sidebar() {
  const { t } = useTranslation();
  const collapsed = useSidebarStore((state) => state.collapsed);
  const setCollapsed = useSidebarStore((state) => state.setCollapsed);

  return (
    <nav
      aria-label={t("nav.sections")}
      className={cn(
        "hidden shrink-0 flex-col overflow-y-auto overflow-x-hidden border-r border-rule bg-panel py-4 transition-[width] duration-200 ease-out motion-reduce:transition-none lg:flex",
        collapsed ? "w-18 px-2.5" : "w-62 px-3",
      )}
    >
      <SidebarBody
        collapsed={collapsed}
        control={
          <button
            type="button"
            aria-label={collapsed ? t("nav.expand") : t("nav.collapse")}
            onClick={() => setCollapsed(!collapsed)}
            className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg text-ink-2 transition-colors hover:bg-panel-2 hover:text-ink motion-reduce:transition-none"
          >
            {collapsed ? (
              <PanelLeftOpen aria-hidden="true" className="size-4" />
            ) : (
              <PanelLeftClose aria-hidden="true" className="size-4" />
            )}
          </button>
        }
      />
    </nav>
  );
}

/** The same pages inside the mobile drawer: never collapsed, with a close button where the collapse button is. */
export function DrawerNavigation({
  onNavigate,
  onClose,
  closeRef,
}: {
  onNavigate: () => void;
  onClose: () => void;
  closeRef: Ref<HTMLButtonElement>;
}) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("nav.sections")} className="flex min-h-full flex-col px-3 pb-7 pt-4">
      <SidebarBody
        collapsed={false}
        onNavigate={onNavigate}
        control={
          <button
            ref={closeRef}
            type="button"
            aria-label={t("nav.closeMenu")}
            onClick={onClose}
            className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg text-ink-2 transition-colors hover:bg-panel-2 hover:text-ink motion-reduce:transition-none"
          >
            <X aria-hidden="true" className="size-4" />
          </button>
        }
      />
    </nav>
  );
}
