import { useEffect, useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Waveform from '../components/Waveform'
import { useAuth } from '../context/AuthContext'
import {
  getProcessingStatus,
  transcribeAudio,
} from '../lib/api'

const STEPS = [
  { id: 'uploading', label: 'Uploading your file' },
  { id: 'waveform', label: 'Generating waveform' },
  { id: 'transcribing', label: 'Transcribing audio' },
  { id: 'scanning', label: 'Scanning for issues' },
  { id: 'ready', label: 'Ready to edit' },
]

// Map backend step → UI step index.
const STEP_INDEX = {
  uploading: 0,
  waveform: 1,
  transcribing: 2,
  scanning: 3,
  ready: 4,
}

export default function Processing() {
  const navigate = useNavigate()
  const location = useLocation()
  const { getToken } = useAuth()
  const project = location.state?.project

  const [status, setStatus] = useState({ step: 'uploading', progress: 0.1, complete: false })
  const [error, setError] = useState(null)
  const transcribeStartedRef = useRef(false)

  // Without a project we have nothing to track — kick back to the dashboard.
  useEffect(() => {
    if (!project?.id) {
      navigate('/dashboard', { replace: true })
    }
  }, [project, navigate])

  // Poll real backend status. Trigger transcription once when we land here
  // with audio uploaded but no transcript yet.
  useEffect(() => {
    if (!project?.id) return
    let cancelled = false
    let timeoutId = null

    const tick = async () => {
      try {
        const s = await getProcessingStatus({ id: project.id, getToken })
        if (cancelled) return
        setStatus(s)

        // Kick off transcription the first time we see "transcribing".
        if (
          s.step === 'transcribing' &&
          !s.complete &&
          !transcribeStartedRef.current
        ) {
          transcribeStartedRef.current = true
          transcribeAudio({ id: project.id, getToken }).catch((err) => {
            if (!cancelled) setError(err.message || 'Transcription failed')
          })
        }

        if (s.complete) {
          // Hold on the "Ready" state briefly so the user sees it tick over.
          timeoutId = setTimeout(() => {
            if (!cancelled) navigate('/editor', { state: { project } })
          }, 600)
          return
        }
      } catch (err) {
        if (!cancelled) setError(err.message || 'Could not check status')
      }
      if (!cancelled) timeoutId = setTimeout(tick, 1500)
    }

    tick()
    return () => {
      cancelled = true
      if (timeoutId) clearTimeout(timeoutId)
    }
  }, [project, navigate, getToken])

  const activeIndex = STEP_INDEX[status.step] ?? 0
  const displayName = project?.name || 'audio.mp3'
  const displayDuration = project?.duration || '—'

  const getStepState = (index) => {
    if (status.complete) return index <= activeIndex ? 'done' : 'pending'
    if (index < activeIndex) return 'done'
    if (index === activeIndex) return 'active'
    return 'pending'
  }

  return (
    <div className="min-h-screen bg-white flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-lg animate-fade-in">
        <div className="text-center mb-8">
          <p className="text-sm text-gray-400 font-mono">
            {displayName.includes('.') ? displayName : `${displayName}.mp3`} · {displayDuration}
          </p>
        </div>

        <div className="mb-10 waveform-pulse">
          <Waveform seed={project?.id || 42} muted height={56} bars={90} />
        </div>

        <div className="space-y-3 mb-10">
          {STEPS.map((step, i) => {
            const state = getStepState(i)
            return (
              <div
                key={step.id}
                className={`flex items-center gap-3 transition-opacity duration-300 ${state === 'pending' ? 'opacity-40' : 'opacity-100'}`}
              >
                <div className="w-5 h-5 flex-shrink-0 flex items-center justify-center">
                  {state === 'done' ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="text-emerald-500">
                      <circle cx="12" cy="12" r="10" fill="currentColor" opacity="0.15" />
                      <path d="M8 12l3 3 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  ) : state === 'active' ? (
                    <svg className="spinner text-accent-500" width="18" height="18" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" strokeOpacity="0.2" />
                      <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                  ) : (
                    <div className="w-2 h-2 rounded-full bg-gray-300 mx-auto" />
                  )}
                </div>

                <span className={`text-sm font-medium ${state === 'done' ? 'text-gray-900' : state === 'active' ? 'text-gray-900' : 'text-gray-400'}`}>
                  {step.label}
                </span>

                {state === 'done' && (
                  <span className="text-xs text-emerald-500 ml-auto">Done</span>
                )}
                {state === 'active' && (
                  <span className="text-xs text-accent-500 ml-auto animate-pulse">In progress</span>
                )}
              </div>
            )
          })}
        </div>

        {error ? (
          <div className="text-center mb-8">
            <p className="text-xs text-red-500 mb-3">{error}</p>
            <button
              onClick={() => navigate('/dashboard')}
              className="text-xs text-gray-500 underline hover:text-gray-700"
            >
              Back to dashboard
            </button>
          </div>
        ) : (
          <p className="text-xs text-gray-400 text-center mb-8">
            Transcription usually takes 10–30 seconds
          </p>
        )}
      </div>

      <div className="fixed bottom-0 left-0 right-0 h-0.5 bg-gray-100">
        <div
          className="h-full bg-accent-500 transition-all duration-300 ease-out"
          style={{ width: `${Math.round((status.progress || 0) * 100)}%` }}
        />
      </div>
    </div>
  )
}
