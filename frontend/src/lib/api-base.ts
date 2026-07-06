// Central API base URL for Tauri vs browser mode

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

if (isTauri && !isViteDev) {
  apiBase = 'http://127.0.0.1:8888'
}

export function setApiBase(port: number) {
  apiBase = `http://127.0.0.1:${port}`
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
