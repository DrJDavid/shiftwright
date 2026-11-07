import type { Role } from '../contracts'

// Categorical role colors, chosen to stay distinct on a washed-out projector.
// 14 hues (one per demo-store role) before any repeats; red is reserved for gaps.
const PALETTE = [
  '#15232d', '#2e62b0', '#c0661a', '#2f8a4c', '#7a4fb0', '#1f8496', '#a23b6e',
  '#6b7a1e', '#8a5a2b', '#c49a00', '#6f9ce6', '#5fb39f', '#c58fd6', '#7d8a96',
]

export function roleColors(roles: Role[]): Map<string, string> {
  return new Map(roles.map((r, i) => [r.id, PALETTE[i % PALETTE.length]]))
}
