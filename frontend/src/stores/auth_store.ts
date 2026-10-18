import { defineStore } from 'pinia'

import { authApi, type AuthUserOut } from '@/api/auth_api'
import { avatarApi } from '@/api/avatar_api'
import { clearSession, readAccessToken, writeSession } from '@/api/session'
import { forgetUnlockedKeys } from '@/crypto/download'
import { forgetSeenShares } from '@/utils/seen-shares'
import { forgetAssistantSession } from '@/utils/assistant-session'

/**
 * Two letters for the avatar. `jlii0421` has no second word to take an initial from, so a
 * single-word name falls back to its first two characters rather than rendering one lonely
 * letter in a circle sized for two.
 */
function toInitials(username: string): string {
  const parts = username.split(/[^A-Za-z0-9]+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: readAccessToken(),
    user: null as AuthUserOut | null,
    /** Object URL for the current avatar image; revoked when replaced or cleared. */
    avatarObjectUrl: null as string | null,
  }),
  getters: {
    isAuthed: (state) => Boolean(state.accessToken),
    /** The header renders before `/auth/me` answers, so this has to survive a null user. */
    displayName: (state) => state.user?.username ?? 'Account',
    initials: (state) => (state.user ? toInitials(state.user.username) : '?'),
    isAdmin: (state) => state.user?.role === 'ADMIN',
    /**
     * An administrator reset this account's login password to a temporary one. The server
     * refuses every route but the few needed to choose a new one; the router guard sends the
     * holder to Settings so they meet the card instead of a page of errors.
     */
    mustChangePassword: (state) => state.user?.must_change_password === true,
    /** ADMIN and RECOVERY_OFFICER can review recovery requests. */
    isRecoveryReviewer: (state) => {
      const role = state.user?.role
      return role === 'ADMIN' || role === 'RECOVERY_OFFICER'
    },
  },
  actions: {
    /**
     * Both tokens, together.
     *
     * The refresh token was previously dropped on the floor at login, which is why a
     * session died 30 minutes in: the credential that exists to renew it was never stored.
     */
    setSession(accessToken: string, refreshToken: string) {
      this.accessToken = accessToken
      writeSession({ accessToken, refreshToken })
    },
    /** Adopt a token the refresh interceptor has already written to storage. */
    syncFromStorage() {
      this.accessToken = readAccessToken()
    },
    /**
     * Keep the account the login response already carries.
     *
     * Login returns the same `user` object as `/auth/me`. Storing it here means the guard
     * knows about `must_change_password` on the very first navigation after signing in,
     * instead of only after the account menu has asked `/auth/me` for it.
     */
    adoptUser(user: AuthUserOut) {
      this.user = user
    },
    /**
     * The server answered `password_change_required`, so the account carries the marker even
     * if what this tab last heard from `/auth/me` said otherwise. Keeping it here is what
     * stops the guard letting the holder straight back to the page that failed.
     */
    markPasswordChangeRequired() {
      if (this.user && !this.user.must_change_password) {
        this.user = { ...this.user, must_change_password: true }
      }
    },
    _revokeAvatarUrl() {
      if (this.avatarObjectUrl) {
        URL.revokeObjectURL(this.avatarObjectUrl)
        this.avatarObjectUrl = null
      }
    },
    /**
     * Fetch the authenticated avatar bytes into a blob URL for `<img>` tags.
     * Failures leave initials visible — the menu must not break when the image is missing.
     */
    async refreshAvatarImage() {
      this._revokeAvatarUrl()
      if (!this.accessToken || !this.user?.has_avatar) return
      try {
        const response = await avatarApi.download()
        const contentType =
          (response.headers?.['content-type'] as string | undefined) || 'image/jpeg'
        const blob = new Blob([response.data], { type: contentType })
        this.avatarObjectUrl = URL.createObjectURL(blob)
      } catch {
        this.avatarObjectUrl = null
      }
    },
    /**
     * Who is signed in, for the avatar and the profile page.
     *
     * Cached, because every authenticated screen wants the same answer and the identity does
     * not change mid-session. A failure leaves `user` null instead of throwing: the account
     * menu is navigation chrome, and it must not be the thing that breaks a working page.
     */
    async loadUser(force = false) {
      if (!this.accessToken) {
        this.user = null
        this._revokeAvatarUrl()
        return null
      }
      if (this.user && !force) return this.user
      try {
        const response = await authApi.me()
        this.user = response.data?.data?.user ?? null
      } catch {
        this.user = null
      }
      await this.refreshAvatarImage()
      return this.user
    },
    /** Upload a new profile picture and refresh the cached image. */
    async uploadAvatar(file: File | Blob) {
      await avatarApi.upload(file)
      if (this.user) this.user = { ...this.user, has_avatar: true }
      await this.refreshAvatarImage()
    },
    /** Remove the profile picture and fall back to initials. */
    async deleteAvatar() {
      await avatarApi.delete()
      if (this.user) this.user = { ...this.user, has_avatar: false }
      this._revokeAvatarUrl()
    },
    /**
     * Drop the local session only.
     *
     * Used when the server has already ended the session (expiry, account deletion) or when
     * there is no usable token left to present to `POST /auth/logout`.
     */
    clearLocalSession() {
      this.accessToken = ''
      // Otherwise the next account to sign in at this machine inherits the previous one's
      // name and email in the avatar menu until `/auth/me` answers.
      this.user = null
      this._revokeAvatarUrl()
      clearSession()
      // The unwrapped account key outlives the token otherwise: the next person at this
      // machine would sign in and find the previous session's files already decryptable.
      forgetUnlockedKeys()
      // The next person to sign in at this machine should not inherit a marker saying they
      // have already seen the previous account's shared files.
      forgetSeenShares()
      // Nor the questions the last account asked the Help assistant about its files.
      forgetAssistantSession()
    },
    /**
     * End the session the user asked to leave.
     *
     * Until #89 the UI only cleared the browser. The refresh token stayed valid on the
     * server, so a stolen copy from before "Log out" could still renew access. Call
     * `POST /auth/logout` first while the bearer is still present, then clear locally
     * even if the server call fails — the user asked to leave this machine either way.
     */
    async logout() {
      if (this.accessToken) {
        try {
          await authApi.logout()
        } catch {
          // Local clear still runs: a dead network must not trap the user as "signed in".
        }
      }
      this.clearLocalSession()
    },
  },
})
