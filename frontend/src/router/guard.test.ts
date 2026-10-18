import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'

import { useAuthStore } from '@/stores/auth_store'
import { authGuard, HOME_AFTER_LOGIN, LOGIN_PATH, PASSWORD_CHANGE_REQUIRED, SETTINGS_PATH } from './guard'

// The auth store reads the token out of localStorage as it initialises, and this suite
// runs in node. A map is enough: the guard only ever asks whether a token is present.
const store = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => void store.set(key, value),
  removeItem: (key: string) => void store.delete(key),
  clear: () => store.clear(),
})

/** Only the three fields the guard reads. */
const route = (path: string, meta: Record<string, unknown> = {}) =>
  ({ path, fullPath: path, meta }) as unknown as RouteLocationNormalized

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

const signIn = () => useAuthStore().setSession('token-for-the-test', 'refresh-for-the-test')

/** The account as login and `/auth/me` report it, with the administrator reset marker set. */
const signInWithTemporaryPassword = () => {
  signIn()
  useAuthStore().adoptUser({
    id: '1',
    username: 'reset-me',
    email: 'reset-me@example.com',
    role: 'USER',
    status: 'ACTIVE',
    email_verified: true,
    created_at: '2026-01-01T00:00:00Z',
    last_login_at: null,
    has_avatar: false,
    must_change_password: true,
  })
}

describe('authGuard', () => {
  it('lets a signed-in visitor through to a protected page', () => {
    signIn()
    expect(authGuard(route('/files', { requiresAuth: true }))).toBeUndefined()
  })

  it('leaves public pages alone either way', () => {
    expect(authGuard(route('/education'))).toBeUndefined()
    signIn()
    expect(authGuard(route('/education'))).toBeUndefined()
  })

  it('sends a signed-out visitor to log in, remembering where they were going', () => {
    // Without the query the visitor logs in and lands somewhere else entirely, having to
    // find their way back to the page they clicked.
    expect(authGuard(route('/files', { requiresAuth: true }))).toEqual({
      path: LOGIN_PATH,
      query: { redirect: '/files' },
    })
  })

  it('does not strand a signed-in visitor on the login page', () => {
    signIn()
    expect(authGuard(route('/login', { guestOnly: true }))).toBe(HOME_AFTER_LOGIN)
  })

  it('lands a signed-in visitor on a page that offers a choice, not on the upload form', () => {
    // The regression this replaces: signing in went straight to /upload, so someone who
    // came back to share or download an earlier file was put in front of the encryption
    // form instead, with no link onward to /files or /audit-logs.
    signIn()
    expect(authGuard(route('/login', { guestOnly: true }))).not.toBe('/upload')
    expect(HOME_AFTER_LOGIN).toBe('/dashboard')
  })

  it('honours an explicit destination over the default landing page', () => {
    const sent = authGuard(route('/audit-logs', { requiresAuth: true }))
    expect(sent).toEqual({ path: LOGIN_PATH, query: { redirect: '/audit-logs' } })
  })


  describe('after an administrator reset the login password', () => {
    it('sends every signed-in page to the Login password card', () => {
      // The temporary password has been seen by the administrator; nothing else should be
      // reachable until the holder has replaced it.
      signInWithTemporaryPassword()
      expect(authGuard(route('/files', { requiresAuth: true }))).toEqual(PASSWORD_CHANGE_REQUIRED)
      expect(authGuard(route('/dashboard', { requiresAuth: true }))).toEqual(PASSWORD_CHANGE_REQUIRED)
    })

    it('never blocks Settings itself, or the redirect could loop forever', () => {
      signInWithTemporaryPassword()
      expect(authGuard(route(SETTINGS_PATH, { requiresAuth: true }))).toBeUndefined()
      expect(PASSWORD_CHANGE_REQUIRED).toMatchObject({ path: SETTINGS_PATH, hash: '#login-password' })
    })

    it('leaves public pages alone and still keeps guests off protected ones', () => {
      signInWithTemporaryPassword()
      expect(authGuard(route('/education'))).toBeUndefined()
      useAuthStore().clearLocalSession()
      expect(authGuard(route('/files', { requiresAuth: true }))).toEqual({
        path: LOGIN_PATH,
        query: { redirect: '/files' },
      })
    })

    it('does nothing for an account that chose its own password', () => {
      signInWithTemporaryPassword()
      const auth = useAuthStore()
      auth.user = { ...auth.user!, must_change_password: false }
      expect(authGuard(route('/files', { requiresAuth: true }))).toBeUndefined()
    })
  })
})
