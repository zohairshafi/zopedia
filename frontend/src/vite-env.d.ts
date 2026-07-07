// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Zopedia team. All rights reserved. See /studio/LICENSE.AGPL-3.0

/// <reference types="vite/client" />

interface ImportMetaEnv {
  // "client" → lightweight client SPA that connects to a remote server.
  // Undefined → full co-located server build. See `vite build --mode client`.
  readonly VITE_ZOPEDIA_MODE?: string;
}
