import { Button } from '../ui/Button'
import { useOptionalTheme } from './theme-context'

function SunIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M20.99 13.2A8 8 0 1 1 10.8 3.01 6.5 6.5 0 0 0 20.99 13.2Z" />
    </svg>
  )
}

export function ThemeToggle() {
  const themeContext = useOptionalTheme()
  if (themeContext == null) return null

  const { theme, toggleTheme } = themeContext
  const isDark = theme === 'dark'
  const nextThemeLabel = isDark ? 'light' : 'dark'

  return (
    <Button
      type="button"
      variant="default"
      onClick={toggleTheme}
      aria-label={`Switch to ${nextThemeLabel} theme. Current theme is ${theme}.`}
      aria-pressed={!isDark}
      title={`Switch to ${nextThemeLabel} theme`}
      leftIcon={isDark ? <MoonIcon /> : <SunIcon />}
    >
      <span className="hidden sm:inline">{isDark ? 'Dark' : 'Light'}</span>
      <span className="sm:hidden" aria-hidden="true">Theme</span>
    </Button>
  )
}
