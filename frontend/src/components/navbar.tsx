// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";

export function Navbar() {
  const { isMobile } = useSidebar();
  if (!isMobile) {
    return (
      <header className="absolute top-0 inset-x-0 z-40 h-[48px] pointer-events-none" />
    );
  }
  return (
    <header className="absolute top-0 inset-x-0 z-40 h-[calc(48px+env(safe-area-inset-top,0px))] pointer-events-none">
      <div className="flex h-full items-start pt-[calc(11px+env(safe-area-inset-top,0px))] pl-2">
        <SidebarTrigger className="pointer-events-auto !size-[34px]" />
      </div>
    </header>
  );
}
