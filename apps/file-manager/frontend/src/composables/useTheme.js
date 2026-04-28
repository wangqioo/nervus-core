import { ref, watch } from 'vue'

// Always follow OS preference — no manual override or localStorage.
// The file manager is an embedded component of Nervus and must share the same
// dark/light state as the parent shell.
const mq = window.matchMedia('(prefers-color-scheme: dark)')
const theme = ref(mq.matches ? 'dark' : 'light')

function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t)
}

applyTheme(theme.value)
watch(theme, applyTheme)

// Live-follow OS theme changes
mq.addEventListener('change', e => {
  theme.value = e.matches ? 'dark' : 'light'
})

export function useTheme() {
  // toggle is kept for API compatibility but no longer used in the UI
  function toggle() { theme.value = theme.value === 'dark' ? 'light' : 'dark' }
  return { theme, toggle }
}
