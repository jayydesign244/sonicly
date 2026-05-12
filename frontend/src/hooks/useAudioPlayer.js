import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'

export function useAudioPlayer({ url, height = 60, color = '#6366f1', ghostColor = '#e5e7eb' } = {}) {
  const containerRef = useRef(null)
  const wsRef = useRef(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isReady, setIsReady] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!url || !containerRef.current) return

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: ghostColor,
      progressColor: color,
      cursorColor: '#9ca3af',
      cursorWidth: 1,
      barWidth: 3,
      barGap: 2,
      barRadius: 2,
      height,
      normalize: true,
      url,
    })
    wsRef.current = ws

    setIsReady(false)
    setError(null)
    setCurrentTime(0)
    setDuration(0)

    const onReady = () => { setDuration(ws.getDuration()); setIsReady(true) }
    const onPlay = () => setIsPlaying(true)
    const onPause = () => setIsPlaying(false)
    const onFinish = () => setIsPlaying(false)
    const onTimeUpdate = (t) => setCurrentTime(t)
    const onError = (e) => setError(typeof e === 'string' ? e : e?.message || 'Failed to load audio')

    ws.on('ready', onReady)
    ws.on('play', onPlay)
    ws.on('pause', onPause)
    ws.on('finish', onFinish)
    ws.on('timeupdate', onTimeUpdate)
    ws.on('error', onError)

    return () => {
      ws.destroy()
      wsRef.current = null
    }
  }, [url, height, color, ghostColor])

  const toggle = () => wsRef.current?.playPause()
  const skip = (seconds) => {
    const ws = wsRef.current
    if (!ws) return
    const next = Math.max(0, Math.min(ws.getDuration(), ws.getCurrentTime() + seconds))
    ws.setTime(next)
  }
  const setVolume = (v) => wsRef.current?.setVolume(v)
  const setRate = (r) => wsRef.current?.setPlaybackRate(r, true)

  return {
    containerRef,
    isPlaying, isReady, currentTime, duration, error,
    toggle, skip, setVolume, setRate,
  }
}

export function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}
