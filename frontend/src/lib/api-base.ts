// Central API base URL for Tauri vs browser mode
import { isClientMode, SERVER_URL_KEY } from './mode'

declare global {
  interface Window {
    __ZOPEDIA_DESKTOP__?: boolean;
    pywebview?: {
      api: Record<string, (...args: unknown[]) => Promise<unknown>>;
    };
  }
}
let apiBase = ''

const isTauri = typeof window !== 'undefined' && '__TAURI__' in window
const isViteDev = import.meta.env.DEV

if (isClientMode()) {
  // Client build talks to whichever remote server the user connected to.
  // The stored URL is absolute, so even in Vite dev the proxy is bypassed.
  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(SERVER_URL_KEY)
    if (stored) apiBase = stored.replace(/\/+$/, '')
  }
} else if (isTauri && !isViteDev) {
  apiBase = 'http://127.0.0.1:8888'
}

export function setApiBase(port: number) {
  apiBase = `http://127.0.0.1:${port}`
}

// Called by the connect flow after a successful login to point all subsequent
// requests at the chosen server.
export function applyServerUrl(url: string) {
  apiBase = url.replace(/\/+$/, '')
}

export function getApiBase(): string {
  return apiBase
}

export function apiUrl(path: string): string {
  if (path.startsWith('http')) return path
  return `${apiBase}${path}`
}

export { isTauri }

// Desktop pywebview mode. Detected via the launcher's custom user agent
// (set on the WKWebView before the page loads). navigator.userAgent is
// available synchronously on first render, so layout/theme can branch with
// no flash — and a real browser can never have this token. The window flag
// is kept as a secondary signal (injected after load).
const DESKTOP_UA_TOKEN = 'ZopediaDesktop'
function getIsDesktop(): boolean {
  if (typeof window === 'undefined') return false
  if (window.__ZOPEDIA_DESKTOP__ === true) return true
  return navigator.userAgent.indexOf(DESKTOP_UA_TOKEN) !== -1
}

export { getIsDesktop }
