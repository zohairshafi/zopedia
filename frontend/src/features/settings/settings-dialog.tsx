// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { useRef, useEffect } from "react";
import { Content as RadixContent } from "@radix-ui/react-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  Cancel01Icon,
  Key01Icon,
  Message01Icon,
  PaintBrush02Icon,
  Settings02Icon,
  SparklesIcon,
  UserAdd02Icon,
  UserIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { motion, useReducedMotion } from "motion/react";
import { isServerMode } from "@/lib/mode";
import { getPermissions } from "@/features/auth";
import { useIsMobile } from "@/hooks/use-mobile";
import { useSettingsDialogStore, type SettingsTab } from "./stores/settings-dialog-store";
import { AboutTab } from "./tabs/about-tab";
import { ApiKeysTab } from "./tabs/api-keys-tab";
import { AppearanceTab } from "./tabs/appearance-tab";
import { ChatTab } from "./tabs/chat-tab";
import { GeneralTab } from "./tabs/general-tab";
import { ProfileTab } from "./tabs/profile-tab";
import { UsersTab } from "./tabs/users-tab";

interface TabDef {
  id: SettingsTab;
  label: string;
  icon: typeof Settings02Icon;
}

const TABS: TabDef[] = [
  { id: "general", label: "General", icon: Settings02Icon },
  { id: "profile", label: "Profile", icon: UserIcon },
  { id: "appearance", label: "Appearance", icon: PaintBrush02Icon },
  { id: "chat", label: "Chat", icon: Message01Icon },
  { id: "api-keys", label: "API Keys", icon: Key01Icon },
  { id: "users", label: "Users", icon: UserAdd02Icon },
  { id: "about", label: "About", icon: SparklesIcon },
];


function renderTab(tab: SettingsTab) {
  switch (tab) {
    case "general":
      return <GeneralTab />;
    case "profile":
      return <ProfileTab />;
    case "appearance":
      return <AppearanceTab />;
    case "chat":
      return <ChatTab />;
    case "api-keys":
      return <ApiKeysTab />;
    case "users":
      return <UsersTab />;
    case "about":
      return <AboutTab />;
  }
}

export function SettingsDialog() {
  const open = useSettingsDialogStore((s) => s.open);
  const activeTab = useSettingsDialogStore((s) => s.activeTab);
  const setActiveTab = useSettingsDialogStore((s) => s.setActiveTab);
  const closeDialog = useSettingsDialogStore((s) => s.closeDialog);
  const reduced = useReducedMotion();
  const isMobile = useIsMobile();
  const tabBarRef = useRef<HTMLDivElement>(null);

  // Compute visible tabs at render time so permission changes take effect.
  const visibleTabs = (() => {
    // API Keys tab is server-only (requires direct server access).
    const tabs = isServerMode() ? TABS : TABS.filter((t) => t.id !== "api-keys");
    // Users tab requires admin — works in both server and client mode.
    if (!getPermissions().is_admin) {
      return tabs.filter((t) => t.id !== "users");
    }
    return tabs;
  })();

  // On mobile, scroll the active tab into view when it changes
  useEffect(() => {
    if (!isMobile || !tabBarRef.current) return;
    const activeBtn = tabBarRef.current.querySelector(
      `[data-tab="${activeTab}"]`,
    ) as HTMLElement | null;
    activeBtn?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [activeTab, isMobile]);

  const TabButton = ({ tab }: { tab: TabDef }) => {
    const active = activeTab === tab.id;
    return (
      <button
        key={tab.id}
        type="button"
        data-tab={tab.id}
        onClick={() => setActiveTab(tab.id)}
        className={cn(
          "relative flex items-center gap-2.5 rounded-[8px] px-2.5 text-sm font-medium transition-colors shrink-0",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background",
          isMobile ? "h-[44px]" : "h-[30px]",
          active
            ? "text-black dark:text-white"
            : "text-[#383835] dark:text-[#c7c7c4] hover:bg-[#ececec] dark:hover:bg-[#2e3035] hover:text-black dark:hover:text-white",
        )}
      >
        {active && (
          <motion.span
            layoutId={isMobile ? "settings-active-pill-mobile" : "settings-active-pill"}
            className="absolute inset-0 rounded-[8px] bg-[#ececec] dark:bg-[#2e3035]"
            transition={
              reduced
                ? { duration: 0 }
                : { type: "spring", stiffness: 500, damping: 35, mass: 0.5 }
            }
          />
        )}
        <HugeiconsIcon
          icon={tab.icon}
          strokeWidth={1.5}
          className="relative z-10 size-[18px] shrink-0"
        />
        <span className="relative z-10 whitespace-nowrap">{tab.label}</span>
      </button>
    );
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && closeDialog()}>
      {isMobile ? (
        /* ───── mobile: Radix Content positioned as bottom sheet ───── */
        <DialogPortal>
          <DialogOverlay className="bg-background/40" />
          <RadixContent
            className="fixed z-50 inset-0 flex flex-col border border-border bg-background shadow-border focus:outline-none"
          >
            <DialogTitle className="sr-only">Settings</DialogTitle>
            <DialogDescription className="sr-only">
              Manage your Zopedia preferences.
            </DialogDescription>

            {/* Header: safe-area padding + scrollable tabs + close button */}
            <div
              className="flex shrink-0 items-center border-b border-border bg-muted/20 py-2 pl-2 pr-1"
              style={{ paddingTop: "calc(0.5rem + env(safe-area-inset-top, 0px))" }}
            >
              <div
                ref={tabBarRef}
                className="flex items-center gap-1 overflow-x-auto flex-1 min-w-0"
                style={{ WebkitOverflowScrolling: "touch" }}
              >
                {visibleTabs.map((tab) => (
                  <TabButton key={tab.id} tab={tab} />
                ))}
              </div>
              <button
                type="button"
                onClick={closeDialog}
                className="ml-1 flex size-7 shrink-0 items-center justify-center rounded-[8px] text-[#383835] dark:text-[#c7c7c4] transition-colors hover:bg-[#ececec] dark:hover:bg-[#2e3035] hover:text-black dark:hover:text-white"
                aria-label="Close settings"
              >
                <HugeiconsIcon icon={Cancel01Icon} className="size-4" />
              </button>
            </div>

            {/* Content */}
            <div
              className="flex-1 min-h-0 overflow-y-auto p-4"
              style={{
                WebkitOverflowScrolling: "touch",
                paddingBottom: "calc(1rem + env(safe-area-inset-bottom, 0px))",
              }}
            >
              {renderTab(activeTab)}
            </div>
          </RadixContent>
        </DialogPortal>
      ) : (
        /* ───── desktop: standard DialogContent ───── */
        <DialogContent
          showCloseButton={false}
          overlayClassName="bg-background/40"
          className="p-0 overflow-hidden shadow-border rounded-xl border-border sm:!max-w-none sm:h-[560px] sm:w-[820px]"
        >
          <DialogTitle className="sr-only">Settings</DialogTitle>
          <DialogDescription className="sr-only">
            Manage your Zopedia preferences.
          </DialogDescription>
          <div className="flex h-full min-h-0">
            <aside className="font-heading flex w-[200px] shrink-0 flex-col border-r border-border bg-muted/20 p-2">
              <nav className="flex flex-col gap-0.5">
                {visibleTabs.map((tab) => (
                  <TabButton key={tab.id} tab={tab} />
                ))}
              </nav>
            </aside>
            <main className="relative flex min-w-0 flex-1 flex-col">
              <button
                type="button"
                onClick={closeDialog}
                className="absolute top-3 right-3 z-10 flex size-7 items-center justify-center rounded-[8px] text-[#383835] dark:text-[#c7c7c4] transition-colors hover:bg-[#ececec] dark:hover:bg-[#2e3035] hover:text-black dark:hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="Close settings"
              >
                <HugeiconsIcon icon={Cancel01Icon} className="size-4" />
              </button>
              <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-6">
                {renderTab(activeTab)}
              </div>
            </main>
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
