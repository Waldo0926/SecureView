import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

export type ThemePreference = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'theme'

function systemPrefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === 'light' || preference === 'dark') return preference
  return systemPrefersDark() ? 'dark' : 'light'
}

function isThemePreference(value: string | null): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark'
}

function readStoredPreference(): ThemePreference {
  if (typeof window === 'undefined') return 'system'
  const saved = localStorage.getItem(STORAGE_KEY)
  return isThemePreference(saved) ? saved : 'system'
}

function applyTheme(nextTheme: ResolvedTheme) {
  document.documentElement.classList.toggle('dark', nextTheme === 'dark')
}

/**
 * One preference for the whole app, held at module scope.
 *
 * The header, the account menu, and the settings page all read and write this. Given a ref
 * created per call, changing the theme on the settings page would leave the header's copy
 * showing the old value -- two controls for one setting, disagreeing about what it is.
 */
const preference = ref<ThemePreference>(readStoredPreference())
const resolvedTheme = computed(() => resolveTheme(preference.value))

watch(
  preference,
  (next) => {
    applyTheme(resolveTheme(next))
    localStorage.setItem(STORAGE_KEY, next)
  },
  { immediate: true },
)

export function useTheme() {
  const setPreference = (next: ThemePreference) => {
    preference.value = next
  }

  let mediaQuery: MediaQueryList | null = null

  const onSystemChange = () => {
    if (preference.value === 'system') {
      applyTheme(resolveTheme('system'))
    }
  }

  onMounted(() => {
    mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    mediaQuery.addEventListener('change', onSystemChange)
  })

  onBeforeUnmount(() => {
    mediaQuery?.removeEventListener('change', onSystemChange)
  })

  return { preference, resolvedTheme, setPreference }
}
