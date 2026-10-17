import { useEffect, useRef, useState } from 'react'
import { BrowserMultiFormatReader, type IScannerControls } from '@zxing/browser'
import { Camera } from 'lucide-react'
import { ErrorMessage } from './Feedback'

export function Scanner({ onScan }: { onScan: (barcode: string) => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const controls = useRef<IScannerControls | null>(null)
  const mounted = useRef(true)
  const requestId = useRef(0)
  const [active, setActive] = useState(false)
  const [error, setError] = useState<unknown>()
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      requestId.current += 1
      controls.current?.stop()
    }
  }, [])
  function stop() {
    requestId.current += 1
    controls.current?.stop()
    controls.current = null
    setActive(false)
  }
  async function start() {
    const currentRequest = ++requestId.current
    setError(null)
    setActive(true)
    try {
      const reader = new BrowserMultiFormatReader()
      const scanControls = await reader.decodeFromVideoDevice(
        undefined,
        video.current!,
        (result, _error, scanner) => {
          if (result && mounted.current && currentRequest === requestId.current) {
            onScan(result.getText())
            scanner.stop()
            stop()
          }
        },
      )
      if (!mounted.current || currentRequest !== requestId.current) scanControls.stop()
      else controls.current = scanControls
    } catch (e) {
      if (mounted.current && currentRequest === requestId.current) {
        setError(e)
        setActive(false)
      }
    }
  }
  return (
    <div className="scanner">
      <video ref={video} hidden={!active} muted playsInline aria-label="Barcode camera preview" />
      <button type="button" className="secondary" disabled={active} onClick={start}>
        <Camera size={16} /> Scan with camera
      </button>
      {active && (
        <button type="button" className="text-button" onClick={stop}>
          Stop camera
        </button>
      )}
      <ErrorMessage error={error} />
    </div>
  )
}
