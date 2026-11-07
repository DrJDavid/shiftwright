export function slug(s: string): string {
  return (
    s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '') || 'item'
  )
}

export function uniqueId(taken: string[], base: string): string {
  if (!taken.includes(base)) return base
  let i = 2
  while (taken.includes(`${base}_${i}`)) i++
  return `${base}_${i}`
}
