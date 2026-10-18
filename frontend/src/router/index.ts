import { createRouter, createWebHistory } from 'vue-router'
import { authGuard } from './guard'
import { routes } from './routes'

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to) {
    if (to.hash) {
      return { el: to.hash, top: 96, behavior: 'smooth' }
    }
    return { top: 0, left: 0 }
  },
  routes,
})

router.beforeEach(authGuard)

/**
 * A deploy replaces the hashed files under /assets. A tab opened before it still holds the old
 * index, so the first lazy page it asks for (How it works, the benchmark) points at a file that is
 * gone: the import fails and the click appears to do nothing. Loading the target address afresh
 * fetches the new index and the right files. Once per address, so a real outage cannot loop.
 */
const CHUNK_ERROR = /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS/i
router.onError((error, to) => {
  const message = error instanceof Error ? error.message : String(error)
  if (!CHUNK_ERROR.test(message)) return
  const key = `chunk-reload:${to.fullPath}`
  try {
    if (sessionStorage.getItem(key)) return
    sessionStorage.setItem(key, '1')
  } catch {
    // Without storage the guard cannot remember; reloading once is still the right move.
  }
  window.location.assign(to.fullPath)
})

export default router
