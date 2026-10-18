/**
 * Where the session tokens live, and who to tell when the session is finally gone.
 *
 * Both `http.ts` and the auth store touch these keys. They used to be string literals in
 * each file, which is survivable for one key and not for two that must be cleared together
 * -- a logout that forgot the refresh token would leave a usable credential behind in
 * storage after the access token was gone.
 */
const ACCESS_TOKEN_KEY = 'access_token'
const REFRESH_TOKEN_KEY = 'refresh_token'
const USERNAME_KEY = 'auth_username'

export interface SessionTokens {
  accessToken: string
  refreshToken: string
}

export function readAccessToken(): string {
  return localStorage.getItem(ACCESS_TOKEN_KEY) || ''
}

export function readRefreshToken(): string {
  return localStorage.getItem(REFRESH_TOKEN_KEY) || ''
}

export function readUsername(): string {
  return localStorage.getItem(USERNAME_KEY) || ''
}

export function writeUsername(username: string): void {
  const trimmed = username.trim()
  if (trimmed) {
    localStorage.setItem(USERNAME_KEY, trimmed)
  } else {
    localStorage.removeItem(USERNAME_KEY)
  }
}

export function writeSession(tokens: SessionTokens): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, tokens.accessToken)
  // An empty refresh token is written as an absence rather than as the string "", so
  // `readRefreshToken()` cannot hand a blank credential to the refresh call.
  if (tokens.refreshToken) {
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refreshToken)
  } else {
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  }
}

export function clearSession(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
  localStorage.removeItem(USERNAME_KEY)
}

/**
 * Called when the session cannot be renewed and the user must sign in again.
 *
 * `http.ts` cannot import the store or the router without a cycle -- the store imports the
 * crypto module, and the router imports the pages that import `http`. The app wires this up
 * once at startup instead.
 */
type SessionExpiredHandler = () => void

let sessionExpiredHandler: SessionExpiredHandler | undefined

export function setSessionExpiredHandler(handler: SessionExpiredHandler | undefined): void {
  sessionExpiredHandler = handler
}

export function notifySessionExpired(): void {
  sessionExpiredHandler?.()
}

/**
 * Called when the API refuses a request because an administrator reset the login password
 * and the holder has not chosen their own yet (`password_change_required`). Wired up in
 * `main.ts` for the same reason as the handler above.
 */
type PasswordChangeRequiredHandler = () => void

let passwordChangeRequiredHandler: PasswordChangeRequiredHandler | undefined

export function setPasswordChangeRequiredHandler(handler: PasswordChangeRequiredHandler | undefined): void {
  passwordChangeRequiredHandler = handler
}

export function notifyPasswordChangeRequired(): void {
  passwordChangeRequiredHandler?.()
}
