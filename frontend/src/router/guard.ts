import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth_store'

/**
 * Where a signed-in user lands when they have not asked for anywhere in particular.
 *
 * This used to be `/upload`, which assumed every visit begins with an upload. It does not:
 * someone signing in to share or download a file they uploaded last week was dropped on
 * the encryption form with no way through to the rest of the app.
 */
export const HOME_AFTER_LOGIN = '/dashboard'

/** Where an unauthenticated visitor is sent, carrying the page they were reaching for. */
export const LOGIN_PATH = '/login'

/** The page that holds the Login password card. */
export const SETTINGS_PATH = '/settings'

/**
 * Where an account whose login password an administrator reset is sent, until the holder
 * has chosen a password of their own. The hash lands the page on the card; the query is what
 * the Settings page reads to show the notice even before `/auth/me` has answered.
 */
export const PASSWORD_CHANGE_REQUIRED: RouteLocationRaw = {
  path: SETTINGS_PATH,
  query: { password: 'required' },
  hash: '#login-password',
}

/**
 * Split out of the router so it can be exercised without a DOM: `createWebHistory()` runs
 * at import time in `./index.ts`, and the test environment here is node.
 */
export function authGuard(to: RouteLocationNormalized): RouteLocationRaw | undefined {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isAuthed) {
    return { path: LOGIN_PATH, query: { redirect: to.fullPath } }
  }
  if (to.meta.guestOnly && auth.isAuthed) {
    return HOME_AFTER_LOGIN
  }
  // Only signed-in pages are redirected, and never Settings itself: the holder must always
  // be able to reach the one card that clears the marker. Public pages stay reachable.
  if (to.meta.requiresAuth && auth.mustChangePassword && to.path !== SETTINGS_PATH) {
    return PASSWORD_CHANGE_REQUIRED
  }
  return undefined
}
