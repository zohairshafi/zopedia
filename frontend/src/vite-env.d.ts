// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

/// <reference types="vite/client" />

// Vite's `?inline` CSS import (returns the stylesheet as a string) — used to
// embed KaTeX CSS into the self-contained HTML export.
declare module "*.css?inline" {
  const css: string;
  export default css;
}

interface ImportMetaEnv {
  // "client" → lightweight client SPA that connects to a remote server.
  // Undefined → full co-located server build. See `vite build --mode client`.
  readonly VITE_ZOPEDIA_MODE?: string;
}
