import { createContext, useContext } from 'react'

export type ThemeMode = 'dark' | 'light'

export interface ThemeContextValue {
  theme: ThemeMode
  setTheme: (theme: ThemeMode) => void
  toggleTheme: () => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)

export function useOptionalTheme() {
  return useContext(ThemeContext)
}

export function useTheme() {
  const context = useOptionalTheme()
  if (context == null) {
    throw new Error('useTheme must be used within ThemeProvider')
  }
  return context
}
