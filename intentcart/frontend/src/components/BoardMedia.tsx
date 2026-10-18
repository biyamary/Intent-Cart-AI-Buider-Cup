import { useEffect, useState } from 'react'
import { ImageOff } from 'lucide-react'
import { apiObjectUrl } from '../lib/api'

/** An image served by our API (uploads, AI concepts); fetched with the auth token. */
export function AuthedImage({
  path,
  alt,
  className,
}: {
  path: string
  alt: string
  className?: string
}) {
  const [src, setSrc] = useState<string>()
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let url: string | undefined
    let live = true
    apiObjectUrl(path)
      .then((objectUrl) => {
        url = objectUrl
        if (live) setSrc(objectUrl)
        else URL.revokeObjectURL(objectUrl)
      })
      .catch(() => live && setFailed(true))
    return () => {
      live = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [path])
  if (failed)
    return (
      <span className={`media-fallback ${className ?? ''}`}>
        <ImageOff size={18} /> Image unavailable
      </span>
    )
  return src ? (
    <img className={className} src={src} alt={alt} />
  ) : (
    <span className={`media-loading ${className ?? ''}`} aria-label="Loading image" />
  )
}

/** A third-party product/editorial image; hides itself if the store blocks hotlinking. */
export function RemoteImage({
  src,
  alt,
  className,
}: {
  src: string
  alt: string
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  if (failed)
    return (
      <span className={`media-fallback ${className ?? ''}`}>
        <ImageOff size={18} />
      </span>
    )
  return (
    <img
      className={className}
      src={src}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  )
}

declare global {
  interface Window {
    PinUtils?: { build: () => void }
  }
}

let pinScript: Promise<void> | null = null
function loadPinterest() {
  pinScript ??= new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://assets.pinterest.com/js/pinit.js'
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => {
      pinScript = null
      reject(new Error('Pinterest widget unavailable'))
    }
    document.body.appendChild(script)
  })
  return pinScript
}

/** Pinterest's official Pin widget (no API access needed, no scraping). */
export function PinterestPin({ url, title }: { url: string; title: string }) {
  const [blocked, setBlocked] = useState(false)
  useEffect(() => {
    let live = true
    loadPinterest()
      .then(() => live && window.PinUtils?.build())
      .catch(() => live && setBlocked(true))
    return () => {
      live = false
    }
  }, [url])
  return (
    <div className="pin-embed">
      {blocked ? (
        <a className="pin-fallback" href={url} target="_blank" rel="noopener noreferrer">
          {title || 'Pinterest idea'} ↗
        </a>
      ) : (
        <a data-pin-do="embedPin" data-pin-width="medium" href={url}>
          {title || 'Pinterest idea'}
        </a>
      )}
    </div>
  )
}
