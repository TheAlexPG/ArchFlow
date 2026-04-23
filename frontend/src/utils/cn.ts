/**
 * Minimal className utility — merges truthy class strings.
 * Drop-in subset of clsx without the extra dependency.
 */
export function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(' ')
}
