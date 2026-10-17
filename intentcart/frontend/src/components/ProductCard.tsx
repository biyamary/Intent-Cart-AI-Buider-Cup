import { Check, Shirt, ShoppingBag, Footprints, Sparkles } from 'lucide-react'
import { money, type Product } from '../lib/types'

export function ProductCard({
  product,
  onChoose,
  disabled,
}: {
  product: Product
  onChoose?: () => void
  disabled?: boolean
}) {
  const Icon =
    product.category === 'outfit'
      ? Shirt
      : product.category === 'handbag'
        ? ShoppingBag
        : product.category === 'footwear'
          ? Footprints
          : Sparkles
  return (
    <article className="product-card">
      <div className={`product-illustration colour-${product.colour}`}>
        <Icon size={42} strokeWidth={1.2} />
        <span>{product.colour}</span>
      </div>
      <div className="product-info">
        <span className="eyebrow">
          {product.source === 'seed' ? 'Sample catalog' : product.retailer}
        </span>
        <h4>{product.title}</h4>
        <strong>{money(product.price_minor)}</strong>
        <p className="fine-print">
          {product.price_fetched_at
            ? `Price checked ${new Date(product.price_fetched_at).toLocaleDateString()}`
            : 'Illustrative price · no live offer'}
        </p>
        {onChoose && (
          <button className="secondary small" onClick={onChoose} disabled={disabled}>
            <Check size={14} /> Choose item
          </button>
        )}
        {product.url && (
          <a href={product.url} target="_blank" rel="noreferrer">
            View at retailer ↗
          </a>
        )}
      </div>
    </article>
  )
}
