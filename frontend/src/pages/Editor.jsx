import { useState, useRef, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Waveform from '../components/Waveform'
import { useAuth } from '../context/AuthContext'
import { streamChat } from '../lib/api'
import { useAudioPlayer, formatTime } from '../hooks/useAudioPlayer'

const INITIAL_MESSAGES = []

const TRANSCRIPT_LINES = [
  { time: '00:00', text: 'Welcome back to the show. Today we are talking about, um, the future of AI in audio editing.' },
  { time: '00:14', text: 'So like I was saying last week, the tools have gotten, uh, remarkably good over the past year.' },
  { time: '00:28', text: 'Our guest today has been building in this space for three years and has some really interesting perspective.' },
  { time: '00:42', text: 'Yeah thanks for having me. So, uh, the thing that surprises most people is how, like, accessible this has become.' },
  { time: '00:58', text: 'Before you needed a studio, expensive equipment, a professional engineer. Now literally anyone can do it.' },
  { time: '01:12', text: 'And the quality is, honestly, um, better than what I was getting in a physical studio two years ago.' },
  { time: '01:28', text: 'The noise removal alone is, like, incredible. Thirty seconds and you have a clean recording.' },
  { time: '01:44', text: 'We have been using it for our entire catalog. About, uh, two hundred episodes reprocessed.' },
  { time: '02:00', text: 'The feedback from listeners has been overwhelmingly positive. They notice the difference immediately.' },
]

const FILLER_WORDS = ['um,', 'uh,', 'like,', 'So,']

const VERSIONS = [
  { id: 'original', label: 'Original' },
  { id: 'noise', label: 'After noise removal' },
  { id: 'warmth', label: 'After voice warmth' },
]

const QUICK_CHIPS = [
  { icon: '🎙️', label: 'Clean up audio' },
  { icon: '✂️', label: 'Remove filler words' },
  { icon: '🔊', label: 'Balance volume' },
  { icon: '🎤', label: 'Deeper voice' },
]

/* ─── Export Modal ────────────────────────────────────────────── */
function ExportModal({ onClose }) {
  const [format, setFormat] = useState('mp3')
  const [filename, setFilename] = useState('podcast_ep12_enhanced')
  const [version, setVersion] = useState('warmth')
  const [downloaded, setDownloaded] = useState(false)

  const handleDownload = () => setDownloaded(true)

  return (
    <ModalOverlay onClose={onClose}>
      <div className="w-[520px] max-w-full animate-slide-up">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">Export your audio</h2>
          <CloseButton onClick={onClose} />
        </div>
        <div className="border-t border-gray-100 mb-5" />

        {downloaded ? (
          <div className="py-8 flex flex-col items-center text-center">
            <div className="w-12 h-12 bg-emerald-50 rounded-full flex items-center justify-center mb-3">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" className="text-emerald-500">
                <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="text-sm font-semibold text-gray-900 mb-1">Your file is ready!</p>
            <p className="text-xs text-gray-400 mb-5">{filename}.{format} · 8.4 MB</p>
            <button onClick={onClose} className="btn-ghost text-sm">Back to editor</button>
          </div>
        ) : (
          <div className="space-y-5">
            {/* Version */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-2">Version to export</label>
              <select
                value={version}
                onChange={e => setVersion(e.target.value)}
                className="input-field text-sm"
              >
                <option value="warmth">After voice warmth (latest) ✓</option>
                <option value="noise">After noise removal</option>
                <option value="original">Original</option>
              </select>
            </div>

            {/* Format */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-2">File format</label>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { id: 'mp3', label: 'MP3', sub: 'Best for sharing' },
                  { id: 'wav', label: 'WAV', sub: 'Lossless' },
                  { id: 'm4a', label: 'M4A', sub: 'Apple / Podcasts' },
                ].map(f => (
                  <button
                    key={f.id}
                    onClick={() => setFormat(f.id)}
                    className={`px-3 py-2.5 rounded-lg border text-left transition-colors ${
                      format === f.id
                        ? 'border-accent-500 bg-accent-50'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <div className={`text-sm font-semibold ${format === f.id ? 'text-accent-600' : 'text-gray-800'}`}>
                      {f.label}
                    </div>
                    <div className="text-xs text-gray-400 mt-0.5">{f.sub}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Filename */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-2">Filename</label>
              <input
                type="text"
                value={filename}
                onChange={e => setFilename(e.target.value)}
                className="input-field text-sm"
              />
            </div>

            {/* File size */}
            <div className="flex items-center justify-between text-xs text-gray-400">
              <span>Estimated size: 8.4 MB</span>
            </div>

            {/* Summary */}
            <div className="bg-gray-50 rounded-lg px-3 py-2.5 border border-gray-100">
              <p className="text-xs text-gray-500">
                ✓ Background noise removed · ✓ Reverb reduced · ✓ 34 fillers cut
              </p>
            </div>

            {/* Download */}
            <button
              onClick={handleDownload}
              className="btn-primary w-full py-3 text-sm"
            >
              Download
            </button>
            <p className="text-xs text-gray-400 text-center -mt-2">✓ No watermarks. Ever.</p>
          </div>
        )}
      </div>
    </ModalOverlay>
  )
}

/* ─── Before/After Modal ──────────────────────────────────────── */
function CompareModal({ onClose, onExport }) {
  const [beforePlaying, setBeforePlaying] = useState(false)
  const [afterPlaying, setAfterPlaying] = useState(false)

  return (
    <ModalOverlay onClose={onClose}>
      <div className="w-[680px] max-w-full animate-slide-up">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">Before vs After</h2>
          <CloseButton onClick={onClose} />
        </div>

        {/* Quality Score */}
        <div className="flex items-center justify-center gap-4 py-4">
          <div className="text-center">
            <div className="text-3xl font-bold text-gray-300">42</div>
            <div className="text-xs text-gray-400 mt-0.5">Before</div>
          </div>
          <div className="flex items-center gap-2 text-gray-300">
            <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </div>
          <div className="text-center">
            <div className="text-3xl font-bold text-emerald-500">87</div>
            <div className="text-xs text-gray-400 mt-0.5">After</div>
          </div>
        </div>
        <div className="text-center text-xs text-gray-400 mb-6">Quality score</div>

        <div className="border-t border-gray-100 mb-5" />

        {/* Before */}
        <div className="space-y-2 mb-4">
          <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">Before</span>
          <div className="flex items-center gap-3">
            <button
              onClick={() => { setBeforePlaying(v => !v); setAfterPlaying(false) }}
              className="w-9 h-9 border border-gray-200 rounded-full flex items-center justify-center text-gray-500 hover:bg-gray-50 flex-shrink-0 transition-colors"
            >
              {beforePlaying ? <PauseIcon /> : <PlayIcon />}
            </button>
            <div className="flex-1">
              <Waveform seed={99} muted height={44} bars={90} />
            </div>
            <span className="text-xs text-gray-400 font-mono flex-shrink-0">00:00 / 03:42</span>
          </div>
        </div>

        <div className="border-t border-gray-100 my-4" />

        {/* After */}
        <div className="space-y-2 mb-4">
          <span className="text-xs font-medium text-accent-500 uppercase tracking-wider">After</span>
          <div className="flex items-center gap-3">
            <button
              onClick={() => { setAfterPlaying(v => !v); setBeforePlaying(false) }}
              className="w-9 h-9 bg-accent-500 hover:bg-accent-600 rounded-full flex items-center justify-center text-white flex-shrink-0 transition-colors"
            >
              {afterPlaying ? <PauseIcon /> : <PlayIcon />}
            </button>
            <div className="flex-1">
              <Waveform seed={99} height={44} bars={90} />
            </div>
            <span className="text-xs text-gray-400 font-mono flex-shrink-0">00:00 / 03:42</span>
          </div>
        </div>

        <p className="text-xs text-gray-400 text-center mb-5">
          Playheads are synced — play either to compare
        </p>

        {/* Changes */}
        <div className="bg-gray-50 rounded-lg px-4 py-3 border border-gray-100 mb-5">
          <div className="text-xs font-medium text-gray-700 mb-2">Changes applied</div>
          <ul className="space-y-1.5">
            {[
              'Removed 14dB background noise',
              'Reduced room reverb by 40%',
              'Cut 34 filler words',
              'Normalised loudness to −16 LUFS',
            ].map(item => (
              <li key={item} className="flex items-center gap-2 text-sm text-gray-600">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-emerald-500 flex-shrink-0">
                  <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {item}
              </li>
            ))}
          </ul>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700 transition-colors">
            ← Back to editor
          </button>
          <button onClick={() => { onClose(); onExport() }} className="btn-primary">
            Export
          </button>
        </div>
      </div>
    </ModalOverlay>
  )
}

/* ─── Shared Modal Primitives ──────────────────────────────────── */
function ModalOverlay({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative card shadow-modal p-6 w-full max-h-[90vh] overflow-y-auto">
        {children}
      </div>
    </div>
  )
}

function CloseButton({ onClick }) {
  return (
    <button onClick={onClick} className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-gray-100 text-gray-400 transition-colors">
      <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    </button>
  )
}

function PlayIcon() {
  return (
    <svg width="12" height="14" viewBox="0 0 12 14" fill="currentColor">
      <path d="M0 0l12 7-12 7z" />
    </svg>
  )
}

function PauseIcon() {
  return (
    <svg width="12" height="14" viewBox="0 0 12 14" fill="currentColor">
      <rect x="0" y="0" width="4" height="14" rx="1" />
      <rect x="8" y="0" width="4" height="14" rx="1" />
    </svg>
  )
}

/* ─── Main Editor ─────────────────────────────────────────────── */
export default function Editor() {
  const navigate = useNavigate()
  const location = useLocation()
  const { getToken } = useAuth()
  const project = location.state?.project || { id: 1, name: 'podcast_episode_12', seed: 42 }

  const [showExport, setShowExport] = useState(false)
  const [showCompare, setShowCompare] = useState(false)
  const [showDiagnosis, setShowDiagnosis] = useState(true)
  const [messages, setMessages] = useState(INITIAL_MESSAGES)
  const [inputText, setInputText] = useState('')
  const [activeVersion, setActiveVersion] = useState('warmth')
  const [isEditingName, setIsEditingName] = useState(false)
  const [projectName, setProjectName] = useState(project.name || 'podcast_episode_12')
  const [selectedWord, setSelectedWord] = useState(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [volume, setVolumeState] = useState(80)
  const [rate, setRateState] = useState('1')
  const chatEndRef = useRef(null)

  const audioUrl = project.audio_url || null
  const player = useAudioPlayer({ url: audioUrl })

  useEffect(() => {
    if (player.isReady) {
      player.setVolume(volume / 100)
      player.setRate(parseFloat(rate))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player.isReady])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendToAI = async (userText) => {
    const history = [...messages, { role: 'user', text: userText }]
    setMessages([...history, { role: 'ai', text: '' }])
    setIsStreaming(true)
    try {
      await streamChat({
        projectId: project.id || 1,
        messages: history,
        getToken,
        onDelta: (delta) => {
          setMessages(prev => {
            const next = [...prev]
            const last = next[next.length - 1]
            next[next.length - 1] = { ...last, text: (last.text || '') + delta }
            return next
          })
        },
      })
    } catch (err) {
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = { role: 'ai', text: `⚠️ ${err.message}` }
        return next
      })
    } finally {
      setIsStreaming(false)
    }
  }

  const handleSend = () => {
    const text = inputText.trim()
    if (!text || isStreaming) return
    setInputText('')
    sendToAI(text)
  }

  const handleFixAll = () => {
    if (isStreaming) return
    setShowDiagnosis(false)
    sendToAI('Fix all three issues: background noise, room reverb, and filler words.')
  }

  const isFillerWord = (word) => FILLER_WORDS.some(fw => word.toLowerCase().includes(fw.toLowerCase().replace(',', '')))

  return (
    <div className="h-screen flex flex-col bg-white overflow-hidden">
      {/* Top Bar */}
      <header className="h-12 border-b border-gray-200 flex items-center px-4 gap-4 flex-shrink-0">
        {/* Left */}
        <button
          onClick={() => navigate('/dashboard')}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900 transition-colors flex-shrink-0"
        >
          <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Dashboard
        </button>

        <div className="w-px h-4 bg-gray-200 flex-shrink-0" />

        {/* Centre — editable name */}
        <div className="flex-1 flex justify-center">
          {isEditingName ? (
            <input
              autoFocus
              value={projectName}
              onChange={e => setProjectName(e.target.value)}
              onBlur={() => setIsEditingName(false)}
              onKeyDown={e => e.key === 'Enter' && setIsEditingName(false)}
              className="text-sm font-medium text-gray-900 bg-transparent border-b border-accent-400 focus:outline-none text-center"
            />
          ) : (
            <button
              onClick={() => setIsEditingName(true)}
              className="text-sm font-medium text-gray-900 hover:text-accent-500 transition-colors truncate max-w-xs"
            >
              {projectName}
            </button>
          )}
        </div>

        {/* Right */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-xs text-gray-400 hidden md:block">3:42 · MP3 · 8.4MB</span>
          <button
            onClick={() => setShowCompare(true)}
            className="btn-ghost text-xs flex items-center gap-1.5 py-1.5"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
              <circle cx="9" cy="12" r="7" />
              <circle cx="15" cy="12" r="7" />
            </svg>
            Compare
          </button>
          <button
            onClick={() => setShowExport(true)}
            className="btn-primary text-xs py-1.5"
          >
            Export
          </button>
        </div>
      </header>

      {/* Main Split */}
      <div className="flex-1 flex min-h-0">
        {/* LEFT PANEL — 30% */}
        <div className="w-[30%] min-w-[280px] border-r border-gray-200 flex flex-col bg-white">
          {/* Chat Header */}
          <div className="px-4 py-3 border-b border-gray-100">
            <div className="flex items-center gap-2">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-accent-500">
                <path d="M12 2L13.09 8.26L20 9L13.09 9.74L12 16L10.91 9.74L4 9L10.91 8.26L12 2Z" fill="currentColor" />
              </svg>
              <span className="text-xs font-semibold text-gray-700">AI Assistant</span>
            </div>
          </div>

          {/* Chat content */}
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0">
            {/* Diagnosis card */}
            {showDiagnosis && (
              <div className="border border-accent-200 bg-accent-50/50 rounded-xl p-3.5 animate-fade-in">
                <div className="flex items-start gap-2 mb-2.5">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-accent-500 mt-0.5 flex-shrink-0">
                    <path d="M12 2L13.09 8.26L20 9L13.09 9.74L12 16L10.91 9.74L4 9L10.91 8.26L12 2Z" fill="currentColor" />
                  </svg>
                  <p className="text-xs font-medium text-gray-800">I found 3 things in your audio</p>
                </div>
                <ul className="space-y-1.5 mb-3">
                  <li className="flex items-center gap-2 text-xs text-gray-600">
                    <span className="w-2 h-2 bg-red-400 rounded-full flex-shrink-0" />
                    Background noise — moderate throughout
                  </li>
                  <li className="flex items-center gap-2 text-xs text-gray-600">
                    <span className="w-2 h-2 bg-yellow-400 rounded-full flex-shrink-0" />
                    Room reverb — light echo on voice
                  </li>
                  <li className="flex items-center gap-2 text-xs text-gray-600">
                    <span className="w-2 h-2 bg-yellow-400 rounded-full flex-shrink-0" />
                    34 filler words detected
                  </li>
                </ul>
                <div className="flex items-center gap-2">
                  <button onClick={handleFixAll} className="btn-primary text-xs py-1 px-2.5">
                    Fix all three
                  </button>
                  <button
                    onClick={() => setShowDiagnosis(false)}
                    className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}

            {/* Messages */}
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {msg.role === 'ai' && (
                  <div className="w-5 h-5 bg-accent-100 rounded-full flex items-center justify-center mr-2 mt-0.5 flex-shrink-0">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" className="text-accent-500">
                      <path d="M12 2L13.09 8.26L20 9L13.09 9.74L12 16L10.91 9.74L4 9L10.91 8.26L12 2Z" fill="currentColor" />
                    </svg>
                  </div>
                )}
                <div
                  className={`max-w-[85%] px-3 py-2 rounded-xl text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-accent-500 text-white rounded-br-sm'
                      : 'bg-white border border-gray-200 text-gray-700 rounded-bl-sm shadow-card'
                  }`}
                >
                  {msg.text}
                </div>
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>

          {/* Quick chips */}
          <div className="px-4 py-2 border-t border-gray-100">
            <div className="flex gap-1.5 overflow-x-auto pb-1 no-scrollbar">
              {QUICK_CHIPS.map(chip => (
                <button
                  key={chip.label}
                  onClick={() => {
                    setInputText(chip.label)
                  }}
                  className="flex-shrink-0 flex items-center gap-1 text-xs bg-gray-50 hover:bg-accent-50 border border-gray-200 hover:border-accent-300 text-gray-600 hover:text-accent-600 px-2.5 py-1.5 rounded-full transition-colors"
                >
                  <span>{chip.icon}</span>
                  <span>{chip.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Input */}
          <div className="px-4 py-3 border-t border-gray-200">
            <div className="flex items-center gap-2 border border-gray-200 rounded-lg px-3 py-2 focus-within:ring-2 focus-within:ring-accent-500 focus-within:border-transparent transition-all">
              <input
                type="text"
                placeholder={isStreaming ? 'AI is responding…' : 'Describe what you want...'}
                value={inputText}
                onChange={e => setInputText(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSend()}
                disabled={isStreaming}
                className="flex-1 text-sm text-gray-900 placeholder-gray-400 bg-transparent focus:outline-none disabled:opacity-60"
              />
              <button
                onClick={handleSend}
                disabled={!inputText.trim() || isStreaming}
                className="w-7 h-7 bg-accent-500 hover:bg-accent-600 disabled:bg-gray-200 text-white rounded-md flex items-center justify-center transition-colors flex-shrink-0"
              >
                <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
                </svg>
              </button>
            </div>
          </div>
        </div>

        {/* RIGHT PANEL — 70% */}
        <div className="flex-1 flex flex-col min-h-0 min-w-0">
          {/* TOP HALF — Waveform */}
          <div className="flex-shrink-0 border-b border-gray-100 p-5">
            {/* Waveform */}
            <div className="relative mb-4 min-h-[60px]">
              {audioUrl ? (
                <>
                  <div ref={player.containerRef} className="w-full" />
                  {!player.isReady && !player.error && (
                    <div className="absolute inset-0 flex items-center justify-center text-xs text-gray-400">
                      Loading audio…
                    </div>
                  )}
                  {player.error && (
                    <div className="absolute inset-0 flex items-center justify-center text-xs text-red-500">
                      {player.error}
                    </div>
                  )}
                </>
              ) : (
                <div className="h-[60px] flex items-center justify-center border border-dashed border-gray-200 rounded-lg text-xs text-gray-400">
                  No audio uploaded for this project
                </div>
              )}
            </div>

            {/* Summary chips */}
            <div className="flex flex-wrap gap-1.5 mb-4">
              {['✓ Removed 14dB noise', '✓ Reduced reverb 40%', '✓ Cut 34 filler words', '↑ Quality: 42 → 87'].map(chip => (
                <span key={chip} className="text-xs text-gray-500 bg-gray-50 border border-gray-100 px-2.5 py-1 rounded-full">
                  {chip}
                </span>
              ))}
            </div>

            {/* Playback controls */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1">
                <button
                  onClick={() => player.skip(-10)}
                  disabled={!player.isReady}
                  className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors disabled:opacity-40 disabled:hover:bg-transparent"
                  title="Back 10s"
                >
                  <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12.066 11.2a1 1 0 000 1.6l5.334 4A1 1 0 0019 16V8a1 1 0 00-1.6-.8l-5.334 4z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.066 11.2a1 1 0 000 1.6l5.334 4A1 1 0 0011 16V8a1 1 0 00-1.6-.8l-5.334 4z" />
                  </svg>
                </button>
                <button
                  onClick={player.toggle}
                  disabled={!player.isReady}
                  className="w-9 h-9 bg-accent-500 hover:bg-accent-600 text-white rounded-full flex items-center justify-center transition-colors disabled:opacity-40 disabled:hover:bg-accent-500"
                >
                  {player.isPlaying ? <PauseIcon /> : <PlayIcon />}
                </button>
                <button
                  onClick={() => player.skip(10)}
                  disabled={!player.isReady}
                  className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors disabled:opacity-40 disabled:hover:bg-transparent"
                  title="Forward 10s"
                >
                  <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M11.933 12.8a1 1 0 000-1.6L6.6 7.2A1 1 0 005 8v8a1 1 0 001.6.8l5.333-4z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.933 12.8a1 1 0 000-1.6l-5.333-4A1 1 0 0013 8v8a1 1 0 001.6.8l5.333-4z" />
                  </svg>
                </button>
              </div>
              <span className="text-xs text-gray-400 font-mono">
                {formatTime(player.currentTime)} / {formatTime(player.duration)}
              </span>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} className="text-gray-400">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.536 8.464a5 5 0 010 7.072M12 6a7 7 0 010 12M9.464 8.464a5 5 0 000 7.072" />
                  </svg>
                  <input
                    type="range"
                    className="w-16 accent-accent-500"
                    min="0"
                    max="100"
                    value={volume}
                    onChange={e => {
                      const v = Number(e.target.value)
                      setVolumeState(v)
                      player.setVolume(v / 100)
                    }}
                  />
                </div>
                <select
                  value={rate}
                  onChange={e => {
                    setRateState(e.target.value)
                    player.setRate(parseFloat(e.target.value))
                  }}
                  className="text-xs text-gray-500 border border-gray-200 rounded-md px-1.5 py-0.5 focus:outline-none"
                >
                  <option value="1">1×</option>
                  <option value="1.25">1.25×</option>
                  <option value="1.5">1.5×</option>
                  <option value="2">2×</option>
                </select>
              </div>
            </div>

            {/* Version history */}
            <div className="flex items-center gap-1.5 mt-3 overflow-x-auto">
              {VERSIONS.map(v => (
                <button
                  key={v.id}
                  onClick={() => setActiveVersion(v.id)}
                  className={`flex-shrink-0 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                    activeVersion === v.id
                      ? 'bg-accent-500 text-white border-accent-500'
                      : 'border-gray-200 text-gray-500 hover:border-gray-300 hover:text-gray-700'
                  }`}
                >
                  {v.label}
                </button>
              ))}
              <button className="flex-shrink-0 w-6 h-6 border border-dashed border-gray-300 rounded-full text-gray-400 flex items-center justify-center text-xs hover:border-gray-400 transition-colors">
                +
              </button>
            </div>
          </div>

          {/* BOTTOM HALF — Transcript */}
          <div className="flex-1 flex flex-col min-h-0">
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 flex-shrink-0">
              <span className="text-xs font-semibold text-gray-700">Transcript</span>
              <span className="text-xs text-gray-400">Edit to change audio</span>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-3 space-y-1">
              {TRANSCRIPT_LINES.map((line, i) => (
                <div
                  key={i}
                  className="flex gap-4 py-1.5 px-2 rounded-lg hover:bg-gray-50 group cursor-default transition-colors"
                >
                  <button
                    className="text-xs font-mono text-gray-300 group-hover:text-accent-400 flex-shrink-0 pt-0.5 w-10 text-right transition-colors"
                    onClick={() => {}}
                  >
                    {line.time}
                  </button>
                  <p className="text-sm text-gray-700 leading-relaxed flex-1 flex flex-wrap gap-x-1">
                    {line.text.split(' ').map((word, wi) => {
                      const isFiller = isFillerWord(word)
                      return (
                        <span
                          key={wi}
                          onClick={() => setSelectedWord(selectedWord === `${i}-${wi}` ? null : `${i}-${wi}`)}
                          className={`cursor-pointer relative inline-block ${
                            isFiller
                              ? 'bg-amber-50 text-amber-700 rounded px-0.5 underline decoration-amber-300 decoration-dotted underline-offset-2'
                              : 'hover:text-accent-600 hover:underline hover:underline-offset-2 hover:decoration-accent-300'
                          } ${selectedWord === `${i}-${wi}` ? 'bg-accent-50 text-accent-600 rounded' : ''}`}
                        >
                          {word}{' '}
                          {selectedWord === `${i}-${wi}` && (
                            <span className="absolute -top-8 left-0 z-10 flex items-center gap-1 bg-gray-900 text-white text-xs rounded-lg px-2 py-1 whitespace-nowrap shadow-lg animate-fade-in">
                              <button className="hover:text-accent-300 transition-colors">✏️ Edit</button>
                              <span className="text-gray-600">·</span>
                              <button className="hover:text-red-300 transition-colors">🗑️ Delete</button>
                              <span className="text-gray-600">·</span>
                              <button className="hover:text-accent-300 transition-colors">▶ Jump to</button>
                            </span>
                          )}
                        </span>
                      )
                    })}
                  </p>
                </div>
              ))}
            </div>

            {/* Footer */}
            <div className="px-5 py-2.5 border-t border-gray-100 flex-shrink-0">
              <p className="text-xs text-gray-400">847 words · ~5 min speaking time</p>
            </div>
          </div>
        </div>
      </div>

      {/* Modals */}
      {showExport && <ExportModal onClose={() => setShowExport(false)} />}
      {showCompare && (
        <CompareModal
          onClose={() => setShowCompare(false)}
          onExport={() => setShowExport(true)}
        />
      )}
    </div>
  )
}
