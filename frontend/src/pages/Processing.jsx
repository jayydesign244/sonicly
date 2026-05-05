import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Waveform from '../components/Waveform'

const STEPS = [
  { id: 'upload', label: 'Uploading your file' },
  { id: 'waveform', label: 'Generating waveform' },
  { id: 'transcribe', label: 'Transcribing audio' },
  { id: 'scan', label: 'Scanning for issues' },
]

export default function Processing() {
  const navigate = useNavigate()
  const location = useLocation()
  const project = location.state?.project || { name: 'podcast_episode_12.mp3', duration: '3:42', seed: 42 }

  const [stepIndex, setStepIndex] = useState(0)

  useEffect(() => {
    const timers = []

    timers.push(setTimeout(() => setStepIndex(1), 400))
    timers.push(setTimeout(() => setStepIndex(2), 900))
    timers.push(setTimeout(() => setStepIndex(3), 1600))
    timers.push(setTimeout(() => setStepIndex(4), 2200))
    timers.push(setTimeout(() => navigate('/editor', { state: { project } }), 2800))

    return () => timers.forEach(clearTimeout)
  }, [navigate, project])

  const getStepState = (index) => {
    if (index < stepIndex) return 'done'
    if (index === stepIndex) return 'active'
    return 'pending'
  }

  return (
    <div className="min-h-screen bg-white flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-lg animate-fade-in">
        {/* File info */}
        <div className="text-center mb-8">
          <p className="text-sm text-gray-400 font-mono">
            {project.name.includes('.') ? project.name : `${project.name}.mp3`} · {project.duration || '3:42'}
          </p>
        </div>

        {/* Waveform */}
        <div className="mb-10 waveform-pulse">
          <Waveform seed={project.seed || 42} muted height={56} bars={90} />
        </div>

        {/* Steps */}
        <div className="space-y-3 mb-10">
          {STEPS.map((step, i) => {
            const state = getStepState(i)
            return (
              <div
                key={step.id}
                className={`flex items-center gap-3 transition-opacity duration-300 ${state === 'pending' ? 'opacity-40' : 'opacity-100'}`}
              >
                {/* Icon */}
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

                {/* Label */}
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

        <p className="text-xs text-gray-400 text-center mb-8">
          This usually takes 10–15 seconds
        </p>
      </div>

      {/* Progress bar */}
      <div className="fixed bottom-0 left-0 right-0 h-0.5 bg-gray-100">
        <div
          className="h-full bg-accent-500 transition-all duration-300 ease-out"
          style={{ width: `${(stepIndex / STEPS.length) * 100}%` }}
        />
      </div>
    </div>
  )
}
