import type { ComponentType } from 'react'
import type { CardType } from '../api/protocol'
import { CardFrame, type CardProps } from './CardFrame'
import { PayrollCard } from './PayrollCard'
import { StoreBasicsCard } from './StoreBasicsCard'

// One component per card_type (API.md card catalogue). Props arrive untyped over the wire;
// each component narrows them to its API.md shape.
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- registry is heterogeneous by design
const REGISTRY: Partial<Record<CardType, ComponentType<CardProps<any, any>>>> = {
  store_basics: StoreBasicsCard,
  payroll: PayrollCard,
}

export function ChatCard(p: CardProps<unknown, unknown> & { cardType: CardType; cardId: string }) {
  const C = REGISTRY[p.cardType]
  if (C) return <C {...p} />
  return (
    <CardFrame
      title={p.cardType.replace(/_/g, ' ')}
      status={p.status}
      onCancel={p.onCancel}
      submitLabel="Continue"
      canSubmit={false}
      formId={`unsupported-${p.cardId}`}
    >
      <p className="text-sm text-ink-2">This step isn't available in the web app yet. Skip it to let the conversation continue.</p>
    </CardFrame>
  )
}
