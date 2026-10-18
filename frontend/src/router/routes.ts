import type { RouteRecordRaw } from 'vue-router'
import DashboardPage from '@/pages/DashboardPage.vue'
import LoginPage from '@/pages/LoginPage.vue'
import RegisterPage from '@/pages/RegisterPage.vue'
import ForgotPasswordPage from '@/pages/ForgotPasswordPage.vue'
import UploadPage from '@/pages/UploadPage.vue'
import WorkspacePage from '@/pages/WorkspacePage.vue'
import FileListPage from '@/pages/FileListPage.vue'
import AuditLogPage from '@/pages/AuditLogPage.vue'
import AdminPage from '@/pages/AdminPage.vue'
import CommunityPage from '@/pages/CommunityPage.vue'
import HelpPage from '@/pages/HelpPage.vue'
import TeamPage from '@/pages/TeamPage.vue'
import ProfilePage from '@/pages/ProfilePage.vue'
import SettingsPage from '@/pages/SettingsPage.vue'
import NotFoundPage from '@/pages/NotFoundPage.vue'

/**
 * Every page, apart from the router so the Help assistant's tests can resolve its links against
 * the real table: `./index.ts` calls `createWebHistory()` at import time, which needs a browser.
 */
export const routes: RouteRecordRaw[] = [
  { path: '/', component: DashboardPage },
  { path: '/login', component: LoginPage, meta: { guestOnly: true } },
  { path: '/register', component: RegisterPage, meta: { guestOnly: true } },
  { path: '/forgot-password', component: ForgotPasswordPage, meta: { guestOnly: true } },
  { path: '/dashboard', component: WorkspacePage, meta: { requiresAuth: true } },
  { path: '/upload', component: UploadPage, meta: { requiresAuth: true } },
  { path: '/files', component: FileListPage, meta: { requiresAuth: true } },
  { path: '/audit-logs', component: AuditLogPage, meta: { requiresAuth: true } },
  { path: '/admin', component: AdminPage, meta: { requiresAuth: true } },
  { path: '/profile', component: ProfilePage, meta: { requiresAuth: true } },
  { path: '/settings', component: SettingsPage, meta: { requiresAuth: true } },
  { path: '/education', component: CommunityPage },
  { path: '/help', component: HelpPage },
  // The animated explainer and quick start. Lazy: newcomers land here from Help and the home page.
  { path: '/how-it-works', component: () => import('@/pages/HowItWorksPage.vue') },
  { path: '/team', component: TeamPage },
  // Threat-model evidence (Issue #60). Public and account-free; lazy so it adds nothing to
  // the main bundle.
  { path: '/benchmark/argon2', component: () => import('@/pages/Argon2BenchmarkPage.vue') },
  // Last, so it only catches what nothing above claimed. Without it an unknown URL rendered
  // a blank page, which reads as a broken site rather than a mistyped link.
  { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundPage },
]
