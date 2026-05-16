import { useState, useRef, useEffect, useMemo } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Waveform from '../components/Waveform'
import { useAuth } from '../context/AuthContext'
import {
  streamChat,
  transcribeAudio,
  getProject,
  detectFillers,
  applyEdits,
  listVersions,
  activateVersion,
  cloneVoice,
  exportProject,
} from '../lib/api'
import { useAudioPlayer, formatTime } from '../hooks/useAudioPlayer'
import { usePendingEdits } from '../hooks/usePendingEdits'

const INITIAL_MESSAGES = []

const fmtMMSS = (s) => {
  if (!Number.isFinite(s) || s < 0) s = 0
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
}

const extToLabel = {
  mp3: 'MP3', wav: 'WAV', m4a: 'M4A', aac: 'AAC', flac: 'FLAC',
  ogg: 'OGG', opus: 'OPUS', webm: 'WebM', mp4: 'MP4',
}

const formatFromUrl = (url) => {
  if (!url) return null
  const clean = url.split('?')[0].split('#')[0]
  const ext = clean.includes('.') ? clean.split('.').pop().toLowerCase() : ''
  return extToLabel[ext] || (ext ? ext.toUpperCase() : null)
}

const formatBytesShort = (bytes) => {
  if (!Number.isFinite(bytes) || bytes <= 0) return null
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(2)} GB`
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`
  if (bytes >= 1_000) return `${Math.round(bytes / 1_000)} KB`
  return `${bytes} B`
}

const QUICK_CHIPS = [
  { icon: '🎙️', label: 'Clean up audio' },
  { icon: '✂️', label: 'Remove filler words' },
  { icon: '🔊', label: 'Balance volume' },
  { icon: '🎤', label: 'Deeper voice' },
]

/* ─── Export Modal ────────────────────────────────────────────── */
const FORMAT_OPTIONS = [
  { id: 'mp3', label: 'MP3', sub: '320kbps · best for sharing', bps: 320_000 },
  { id: 'wav', label: 'WAV', sub: '24-bit lossless · best for editing', bps: 24 * 48_000 * 2 },
  { id: 'm4a', label: 'M4A', sub: '256kbps AAC · Apple / Podcasts', bps: 256_000 },
]

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return '—'
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(2)} GB`
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`
  if (bytes >= 1_000) return `${(bytes / 1_000).toFixed(0)} KB`
  return `${bytes} B`
}

function ExportModal({
  onClose,
  projectId,
  projectName,
  versions = [],
  activeVersionId = null,
  durationSec = 0,
  exportHistory = [],
  onExported,
  getToken,
}) {
  // Sort: active first, then newest → oldest by id.
  const versionOptions = useMemo(() => {
    const sorted = [...versions].sort((a, b) => b.id - a.id)
    if (activeVersionId) {
      const idx = sorted.findIndex(v => v.id === activeVersionId)
      if (idx > 0) {
        const [active] = sorted.splice(idx, 1)
        sorted.unshift(active)
      }
    }
    return sorted
  }, [versions, activeVersionId])

  const defaultBase = useMemo(() => {
    const raw = projectName || 'audio'
    return raw.replace(/\.[a-z0-9]{1,5}$/i, '')
  }, [projectName])

  const [format, setFormat] = useState('mp3')
  const [filename, setFilename] = useState(`${defaultBase}_enhanced`)
  const [versionId, setVersionId] = useState(activeVersionId ?? '')
  const [status, setStatus] = useState('idle') // idle | exporting | done | error
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const estimatedBytes = useMemo(() => {
    const bps = FORMAT_OPTIONS.find(f => f.id === format)?.bps || 0
    return Math.round((bps * (durationSec || 0)) / 8)
  }, [format, durationSec])

  const handleDownload = async () => {
    if (!projectId || status === 'exporting') return
    setStatus('exporting')
    setError(null)
    try {
      const res = await exportProject({
        id: projectId,
        format,
        versionId: versionId ? Number(versionId) : null,
        filename,
        getToken,
      })
      // Pull the rendered file as a blob so we can force a clean filename,
      // regardless of the storage backend's URL shape.
      const blob = await fetch(res.download_url).then(r => {
        if (!r.ok) throw new Error(`Download failed (${r.status})`)
        return r.blob()
      })
      const objUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objUrl
      a.download = res.filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(objUrl)

      const record = { ...res, exported_at: new Date().toISOString() }
      setResult(record)
      setStatus('done')
      onExported?.(record)
    } catch (err) {
      setError(err.message || 'Export failed')
      setStatus('error')
    }
  }

  const versionLabel = (v) => {
    const isActive = v.id === activeVersionId
    const dur = v.duration ? ` · ${fmtMMSS(v.duration)}` : ''
    return `${v.label || 'Edit'}${dur}${isActive ? ' ✓' : ''}`
  }

  return (
    <ModalOverlay onClose={onClose}>
      <div className="w-[520px] max-w-full animate-slide-up">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">Export your audio</h2>
          <CloseButton onClick={onClose} />
        </div>
        <div className="border-t border-gray-100 mb-5" />

        {status === 'done' && result ? (
          <div className="py-8 flex flex-col items-center text-center">
            <div className="w-12 h-12 bg-emerald-50 rounded-full flex items-center justify-center mb-3">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" className="text-emerald-500">
                <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="text-sm font-semibold text-gray-900 mb-1">Your file is ready!</p>
            <p className="text-xs text-gray-400 mb-5">
              {result.filename} · {formatBytes(result.size_bytes)}
            </p>
            <div className="flex gap-2">
              <button onClick={() => { setStatus('idle'); setResult(null) }} className="btn-ghost text-sm">
                Export another
              </button>
              <button onClick={onClose} className="btn-primary text-sm">Back to editor</button>
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            {/* Version */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-2">Version to export</label>
              {versionOptions.length === 0 ? (
                <p className="text-xs text-gray-400 px-1">
                  No saved versions yet — original audio will be exported.
                </p>
              ) : (
                <select
                  value={versionId}
                  onChange={e => setVersionId(e.target.value)}
                  className="input-field text-sm"
                >
                  {versionOptions.map(v => (
                    <option key={v.id} value={v.id}>{versionLabel(v)}</option>
                  ))}
                </select>
              )}
            </div>

            {/* Format */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-2">File format</label>
              <div className="grid grid-cols-3 gap-2">
                {FORMAT_OPTIONS.map(f => (
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
              <div className="flex items-stretch gap-2">
                <input
                  type="text"
                  value={filename}
                  onChange={e => setFilename(e.target.value)}
                  className="input-field text-sm flex-1"
                />
                <span className="px-3 flex items-center text-xs text-gray-400 bg-gray-50 border border-gray-200 rounded-lg">
                  .{format}
                </span>
              </div>
            </div>

            {/* File size */}
            <div className="flex items-center justify-between text-xs text-gray-400">
              <span>Estimated size: {formatBytes(estimatedBytes)}</span>
              {durationSec > 0 && <span>{fmtMMSS(durationSec)} duration</span>}
            </div>

            {error && (
              <div className="text-xs text-red-500 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            {/* Download */}
            <button
              onClick={handleDownload}
              disabled={status === 'exporting' || !filename.trim()}
              className="btn-primary w-full py-3 text-sm disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {status === 'exporting' ? (
                <>
                  <svg className="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity="0.25" />
                    <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                  </svg>
                  Rendering…
                </>
              ) : 'Download'}
            </button>
            <p className="text-xs text-gray-400 text-center -mt-2">✓ No watermarks. Ever.</p>

            {/* Export history (this session) */}
            {exportHistory.length > 0 && (
              <div className="border-t border-gray-100 pt-4">
                <p className="text-xs font-medium text-gray-500 mb-2">Exported this session</p>
                <ul className="space-y-1.5 max-h-32 overflow-y-auto">
                  {exportHistory.map((h, i) => (
                    <li
                      key={`${h.filename}-${h.exported_at}-${i}`}
                      className="flex items-center justify-between text-xs text-gray-600 px-2 py-1.5 rounded hover:bg-gray-50"
                    >
                      <span className="truncate">{h.filename}</span>
                      <span className="text-gray-400 flex-shrink-0 ml-2">{formatBytes(h.size_bytes)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
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
  const [exportHistory, setExportHistory] = useState([])
  const [showDiagnosis, setShowDiagnosis] = useState(true)
  const [messages, setMessages] = useState(INITIAL_MESSAGES)
  const [inputText, setInputText] = useState('')
  const [isEditingName, setIsEditingName] = useState(false)
  const [projectName, setProjectName] = useState(project.name || 'podcast_episode_12')
  const [selectedWord, setSelectedWord] = useState(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [volume, setVolumeState] = useState(80)
  const [rate, setRateState] = useState('1')
  const [transcript, setTranscript] = useState(project.transcript || null)
  const [transcriptState, setTranscriptState] = useState(
    project.transcript ? 'ready' : project.audio_url ? 'idle' : 'no-audio'
  )
  const [transcriptError, setTranscriptError] = useState(null)
  const [audioUrl, setAudioUrl] = useState(project.audio_url || null)
  const [fillerRefs, setFillerRefs] = useState([])
  const [versions, setVersions] = useState([])
  const [activeVersionId, setActiveVersionId] = useState(project.active_version_id || null)
  const [applyingEdits, setApplyingEdits] = useState(false)
  const [editError, setEditError] = useState(null)
  const [voiceId, setVoiceId] = useState(project.voice_id || null)
  const [voiceCloning, setVoiceCloning] = useState(false)
  const [inlineEdit, setInlineEdit] = useState(null) // { si, wi, text }
  const [audioSizeBytes, setAudioSizeBytes] = useState(null)
  const pending = usePendingEdits()
  const chatEndRef = useRef(null)
  const activeWordRef = useRef(null)

  const player = useAudioPlayer({ url: audioUrl })

  useEffect(() => {
    if (player.isReady) {
      player.setVolume(volume / 100)
      player.setRate(parseFloat(rate))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player.isReady])

  // Load existing transcript (in case Editor was opened with only an id),
  // or kick off transcription if audio exists but no transcript yet.
  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!project.id) return
      try {
        const fresh = await getProject({ id: project.id, getToken })
        if (cancelled) return
        setAudioUrl(fresh.audio_url || null)
        setActiveVersionId(fresh.active_version_id || null)
        setVoiceId(fresh.voice_id || null)
        if (fresh.transcript) {
          setTranscript(fresh.transcript)
          setTranscriptState('ready')
        } else if (!fresh.audio_url) {
          setTranscriptState('no-audio')
          return
        } else {
          setTranscriptState('transcribing')
          const updated = await transcribeAudio({ id: project.id, getToken })
          if (cancelled) return
          setTranscript(updated.transcript || null)
          setAudioUrl(updated.audio_url || fresh.audio_url || null)
          setTranscriptState(updated.transcript ? 'ready' : 'idle')
        }
        // Fire-and-forget side loads.
        listVersions({ id: project.id, getToken }).then(v => {
          if (!cancelled) setVersions(v || [])
        }).catch(() => {})
      } catch (err) {
        if (cancelled) return
        setTranscriptError(err.message)
        setTranscriptState('error')
      }
    }
    run()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])

  // Whenever the transcript changes (loaded, edited, version switched),
  // re-detect fillers on the server.
  useEffect(() => {
    let cancelled = false
    if (!project.id || transcriptState !== 'ready') {
      setFillerRefs([])
      return
    }
    detectFillers({ id: project.id, getToken })
      .then(res => { if (!cancelled) setFillerRefs(res?.fillers || []) })
      .catch(() => { if (!cancelled) setFillerRefs([]) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, transcript, transcriptState])

  // Find which word is currently being spoken — for live highlight.
  const activeWordKey = useMemo(() => {
    if (!transcript?.segments?.length) return null
    const t = player.currentTime
    for (let si = 0; si < transcript.segments.length; si++) {
      const seg = transcript.segments[si]
      if (t < seg.start - 0.05) break
      if (t > seg.end + 0.25) continue
      for (let wi = 0; wi < seg.words.length; wi++) {
        const w = seg.words[wi]
        if (t >= w.start && t <= w.end + 0.05) return `${si}-${wi}`
      }
    }
    return null
  }, [player.currentTime, transcript])

  useEffect(() => {
    if (activeWordRef.current) {
      activeWordRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }, [activeWordKey])

  const wordCount = useMemo(() => {
    if (!transcript?.segments) return 0
    return transcript.segments.reduce((acc, s) => acc + s.words.length, 0)
  }, [transcript])

  // Filler word lookup — built from the server response, not heuristics.
  const fillerSet = useMemo(() => {
    const s = new Set()
    for (const f of fillerRefs) s.add(`${f.segment_idx}-${f.word_idx}`)
    return s
  }, [fillerRefs])

  const isFillerWord = (si, wi) => fillerSet.has(`${si}-${wi}`)

  const handleRemoveAllFillers = () => {
    if (!fillerRefs.length) return
    pending.queueDeletes(fillerRefs)
  }

  const handleCancelEdits = () => {
    pending.clear()
    setEditError(null)
  }

  const handleConfirmEdits = async () => {
    if (!pending.count || !project.id) return
    setApplyingEdits(true)
    setEditError(null)
    try {
      const version = await applyEdits({
        id: project.id,
        edits: pending.serialize(),
        parentVersionId: activeVersionId,
        getToken,
      })
      pending.clear()
      setActiveVersionId(version.id)
      if (version.audio_url) setAudioUrl(version.audio_url)
      if (version.transcript) setTranscript(version.transcript)
      const [freshVersions, freshProject] = await Promise.all([
        listVersions({ id: project.id, getToken }),
        getProject({ id: project.id, getToken }),
      ])
      setVersions(freshVersions || [])
      if (freshProject?.voice_id) setVoiceId(freshProject.voice_id)
    } catch (err) {
      setEditError(err.message)
    } finally {
      setApplyingEdits(false)
    }
  }

  const handleCloneVoice = async () => {
    if (!project.id || voiceCloning) return
    setVoiceCloning(true)
    setEditError(null)
    try {
      const updated = await cloneVoice({ id: project.id, getToken })
      setVoiceId(updated.voice_id || null)
    } catch (err) {
      setEditError(err.message)
    } finally {
      setVoiceCloning(false)
    }
  }

  const beginInlineEdit = (si, wi, currentText) => {
    setSelectedWord(null)
    setInlineEdit({ si, wi, text: (currentText || '').trim() })
  }

  const commitInlineEdit = () => {
    if (!inlineEdit) return
    const trimmed = inlineEdit.text.trim()
    const original = transcript?.segments?.[inlineEdit.si]?.words?.[inlineEdit.wi]?.text?.trim() || ''
    if (trimmed && trimmed !== original) {
      pending.queueReplace(inlineEdit.si, inlineEdit.wi, trimmed)
    }
    setInlineEdit(null)
  }

  const cancelInlineEdit = () => setInlineEdit(null)

  const handleActivateVersion = async (versionId) => {
    if (!project.id || versionId === activeVersionId) return
    setApplyingEdits(true)
    try {
      const updated = await activateVersion({ id: project.id, versionId, getToken })
      setActiveVersionId(versionId)
      if (updated.audio_url) setAudioUrl(updated.audio_url)
      if (updated.transcript) setTranscript(updated.transcript)
    } catch (err) {
      setEditError(err.message)
    } finally {
      setApplyingEdits(false)
    }
  }

  const retryTranscribe = async () => {
    if (!project.id) return
    setTranscriptError(null)
    setTranscriptState('transcribing')
    try {
      const updated = await transcribeAudio({ id: project.id, getToken })
      setTranscript(updated.transcript || null)
      setTranscriptState(updated.transcript ? 'ready' : 'idle')
    } catch (err) {
      setTranscriptError(err.message)
      setTranscriptState('error')
    }
  }

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Best-effort size lookup for the file-info line. HEAD avoids downloading
  // the bytes; some CDNs don't expose Content-Length so we tolerate failure.
  useEffect(() => {
    let cancelled = false
    setAudioSizeBytes(null)
    if (!audioUrl) return
    fetch(audioUrl, { method: 'HEAD' })
      .then(r => {
        if (cancelled || !r.ok) return
        const len = r.headers.get('Content-Length')
        if (len) setAudioSizeBytes(parseInt(len, 10))
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [audioUrl])

  const fileInfo = useMemo(() => {
    const parts = []
    const dur = transcript?.duration || player.duration
    if (Number.isFinite(dur) && dur > 0) parts.push(fmtMMSS(dur))
    const fmt = formatFromUrl(audioUrl)
    if (fmt) parts.push(fmt)
    const size = formatBytesShort(audioSizeBytes)
    if (size) parts.push(size)
    return parts.join(' · ')
  }, [audioUrl, audioSizeBytes, player.duration, transcript?.duration])

  const diagnosisItems = useMemo(() => {
    const items = []
    if (transcriptState === 'ready' && fillerRefs.length > 0) {
      items.push({
        kind: 'fillers',
        severity: fillerRefs.length > 20 ? 'high' : 'medium',
        text: `${fillerRefs.length} filler word${fillerRefs.length === 1 ? '' : 's'} detected`,
      })
    }
    return items
  }, [transcriptState, fillerRefs.length])

  const summaryChips = useMemo(() => {
    const chips = []
    const activeVersion = versions.find(v => v.id === activeVersionId)
    if (activeVersion) {
      chips.push({ tone: 'good', text: `✓ ${activeVersion.label}` })
    } else if (audioUrl && versions.length === 0) {
      chips.push({ tone: 'muted', text: 'Original audio · no edits yet' })
    } else if (audioUrl && activeVersionId == null) {
      chips.push({ tone: 'muted', text: '↺ Original audio' })
    }
    if (versions.length > 0) {
      chips.push({
        tone: 'muted',
        text: `${versions.length} version${versions.length === 1 ? '' : 's'}`,
      })
    }
    if (fillerRefs.length > 0) {
      chips.push({
        tone: 'warn',
        text: `✂︎ ${fillerRefs.length} filler${fillerRefs.length === 1 ? '' : 's'} detected`,
      })
    }
    if (pending.count > 0) {
      chips.push({
        tone: 'pending',
        text: `● ${pending.count} pending change${pending.count === 1 ? '' : 's'}`,
      })
    }
    if (transcript?.language) {
      chips.push({ tone: 'muted', text: transcript.language.toUpperCase() })
    }
    return chips
  }, [versions, activeVersionId, audioUrl, fillerRefs.length, pending.count, transcript?.language])

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
    let acted = false
    for (const item of diagnosisItems) {
      if (item.kind === 'fillers') {
        handleRemoveAllFillers()
        acted = true
      }
    }
    if (acted) setShowDiagnosis(false)
  }

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
          {fileInfo && (
            <span className="text-xs text-gray-400 hidden md:block">{fileInfo}</span>
          )}
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
            {/* Diagnosis card — only shows when we actually detected something */}
            {showDiagnosis && diagnosisItems.length > 0 && (
              <div className="border border-accent-200 bg-accent-50/50 rounded-xl p-3.5 animate-fade-in">
                <div className="flex items-start gap-2 mb-2.5">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-accent-500 mt-0.5 flex-shrink-0">
                    <path d="M12 2L13.09 8.26L20 9L13.09 9.74L12 16L10.91 9.74L4 9L10.91 8.26L12 2Z" fill="currentColor" />
                  </svg>
                  <p className="text-xs font-medium text-gray-800">
                    {diagnosisItems.length === 1
                      ? 'I found 1 thing in your audio'
                      : `I found ${diagnosisItems.length} things in your audio`}
                  </p>
                </div>
                <ul className="space-y-1.5 mb-3">
                  {diagnosisItems.map(item => {
                    const dotClass =
                      item.severity === 'high'
                        ? 'bg-red-400'
                        : item.severity === 'medium'
                        ? 'bg-yellow-400'
                        : 'bg-gray-300'
                    return (
                      <li key={item.kind} className="flex items-center gap-2 text-xs text-gray-600">
                        <span className={`w-2 h-2 ${dotClass} rounded-full flex-shrink-0`} />
                        {item.text}
                      </li>
                    )
                  })}
                </ul>
                <div className="flex items-center gap-2">
                  <button onClick={handleFixAll} className="btn-primary text-xs py-1 px-2.5">
                    {diagnosisItems.length === 1 ? 'Fix it' : `Fix all ${diagnosisItems.length}`}
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
            {summaryChips.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-4">
                {summaryChips.map((chip, idx) => {
                  const toneClass =
                    chip.tone === 'good'
                      ? 'text-emerald-700 bg-emerald-50 border-emerald-100'
                      : chip.tone === 'warn'
                      ? 'text-amber-700 bg-amber-50 border-amber-200'
                      : chip.tone === 'pending'
                      ? 'text-violet-700 bg-violet-50 border-violet-200'
                      : 'text-gray-500 bg-gray-50 border-gray-100'
                  return (
                    <span
                      key={`${chip.text}-${idx}`}
                      className={`text-xs px-2.5 py-1 rounded-full border ${toneClass}`}
                    >
                      {chip.text}
                    </span>
                  )
                })}
              </div>
            )}

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
            <div className="flex items-center gap-1.5 mt-3 overflow-x-auto no-scrollbar">
              {versions.length === 0 ? (
                <span className="text-xs text-gray-400">Original</span>
              ) : (
                <>
                  <button
                    onClick={() => handleActivateVersion(null)}
                    disabled={applyingEdits}
                    className={`flex-shrink-0 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                      activeVersionId == null
                        ? 'bg-accent-500 text-white border-accent-500'
                        : 'border-gray-200 text-gray-500 hover:border-gray-300 hover:text-gray-700'
                    } disabled:opacity-50`}
                    title="Original audio"
                  >
                    Original
                  </button>
                  {versions.map(v => (
                    <button
                      key={v.id}
                      onClick={() => handleActivateVersion(v.id)}
                      disabled={applyingEdits}
                      className={`flex-shrink-0 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                        activeVersionId === v.id
                          ? 'bg-accent-500 text-white border-accent-500'
                          : 'border-gray-200 text-gray-500 hover:border-gray-300 hover:text-gray-700'
                      } disabled:opacity-50`}
                      title={new Date(v.created_at).toLocaleString()}
                    >
                      {v.label}
                    </button>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* BOTTOM HALF — Transcript */}
          <div className="flex-1 flex flex-col min-h-0">
            <div className="px-5 py-2.5 border-b border-gray-100 flex-shrink-0 flex items-center gap-3 flex-wrap">
              <span className="text-xs font-semibold text-gray-700">Transcript</span>

              {transcriptState === 'ready' && (
                <>
                  <span className="text-xs text-gray-400">
                    {fillerRefs.length} filler{fillerRefs.length === 1 ? '' : 's'} detected
                  </span>
                  {fillerRefs.length > 0 && (
                    <button
                      onClick={handleRemoveAllFillers}
                      className="text-xs px-2 py-1 rounded-md border border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors"
                    >
                      ✂︎ Remove all fillers
                    </button>
                  )}
                </>
              )}

              {editError && (
                <div className="basis-full mt-1 text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1 break-words">
                  {editError}
                </div>
              )}

              <span className="ml-auto flex items-center gap-2">
                {transcriptState === 'ready' && (
                  voiceId ? (
                    <span
                      className="text-[11px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200"
                      title="Voice clone ready — edited words will be regenerated in this voice"
                    >
                      🎙 Voice ready
                    </span>
                  ) : (
                    <button
                      onClick={handleCloneVoice}
                      disabled={voiceCloning || !audioUrl}
                      className="text-[11px] px-1.5 py-0.5 rounded-full bg-gray-50 border border-gray-200 text-gray-600 hover:bg-violet-50 hover:text-violet-700 hover:border-violet-200 disabled:opacity-40"
                      title="Clone your voice from this audio so edited words can be regenerated"
                    >
                      {voiceCloning ? '🎙 Cloning…' : '🎙 Clone voice'}
                    </button>
                  )
                )}
                {pending.count > 0 && (
                  <>
                    <span className="text-xs text-gray-500">
                      {pending.deleteCount > 0 && `${pending.deleteCount} delete${pending.deleteCount === 1 ? '' : 's'}`}
                      {pending.deleteCount > 0 && pending.replaceCount > 0 && ' · '}
                      {pending.replaceCount > 0 && `${pending.replaceCount} replace${pending.replaceCount === 1 ? '' : 's'}`}
                    </span>
                    <button
                      onClick={pending.undo}
                      disabled={applyingEdits}
                      className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-40"
                    >
                      Undo
                    </button>
                    <button
                      onClick={handleCancelEdits}
                      disabled={applyingEdits}
                      className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-40"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleConfirmEdits}
                      disabled={applyingEdits}
                      className="btn-primary text-xs py-1 px-2.5 disabled:opacity-60"
                    >
                      {applyingEdits ? (pending.replaceCount > 0 ? 'Regenerating…' : 'Applying…') : 'Confirm'}
                    </button>
                  </>
                )}
                {pending.count === 0 && (
                  <span className="text-xs text-gray-400 hidden md:inline">
                    Click delete · Double-click edit · Shift+click jump
                  </span>
                )}
              </span>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-3 space-y-1">
              {transcriptState === 'no-audio' && (
                <div className="h-full flex items-center justify-center text-xs text-gray-400">
                  Upload audio to generate a transcript.
                </div>
              )}
              {transcriptState === 'transcribing' && (
                <div className="h-full flex flex-col items-center justify-center gap-2 text-xs text-gray-400">
                  <div className="w-5 h-5 border-2 border-accent-400 border-t-transparent rounded-full animate-spin" />
                  Transcribing audio…
                </div>
              )}
              {transcriptState === 'error' && (
                <div className="h-full flex flex-col items-center justify-center gap-2 text-xs text-red-500 text-center px-4">
                  <span>Transcription failed.</span>
                  {transcriptError && <span className="text-gray-400">{transcriptError}</span>}
                  <button onClick={retryTranscribe} className="btn-ghost text-xs mt-1">Retry</button>
                </div>
              )}
              {transcriptState === 'ready' && transcript?.segments?.map((seg, i) => (
                <div
                  key={i}
                  className="flex gap-4 py-1.5 px-2 rounded-lg hover:bg-gray-50 group cursor-default transition-colors"
                >
                  <button
                    className="text-xs font-mono text-gray-300 group-hover:text-accent-400 flex-shrink-0 pt-0.5 w-10 text-right transition-colors"
                    onClick={() => player.seek(seg.start, { play: true })}
                    title="Jump to this line"
                  >
                    {fmtMMSS(seg.start)}
                  </button>
                  <p className="text-sm text-gray-700 leading-relaxed flex-1 flex flex-wrap gap-x-1">
                    {seg.words.map((w, wi) => {
                      const key = `${i}-${wi}`
                      const filler = isFillerWord(i, wi)
                      const deleted = pending.isDeleted(i, wi)
                      const replacedTo = pending.replacedText(i, wi)
                      const replaced = replacedTo !== undefined
                      const active = activeWordKey === key
                      const selected = selectedWord === key
                      const editing = inlineEdit && inlineEdit.si === i && inlineEdit.wi === wi
                      const original = (w.text || '').trim()

                      if (editing) {
                        return (
                          <span key={wi} className="relative inline-block">
                            <input
                              autoFocus
                              value={inlineEdit.text}
                              onChange={e => setInlineEdit(s => ({ ...s, text: e.target.value }))}
                              onBlur={commitInlineEdit}
                              onKeyDown={e => {
                                if (e.key === 'Enter') { e.preventDefault(); commitInlineEdit() }
                                if (e.key === 'Escape') { e.preventDefault(); cancelInlineEdit() }
                              }}
                              className="px-1 py-0 -my-0.5 text-sm bg-violet-50 border border-violet-300 rounded outline-none focus:ring-1 focus:ring-violet-400 min-w-[60px]"
                              size={Math.max(inlineEdit.text.length, 4)}
                            />{' '}
                          </span>
                        )
                      }

                      const onWordClick = (e) => {
                        if (e.shiftKey) {
                          player.seek(w.start, { play: true })
                          return
                        }
                        if (e.altKey || e.metaKey) {
                          beginInlineEdit(i, wi, original)
                          return
                        }
                        pending.toggleDelete(i, wi)
                      }
                      return (
                        <span
                          key={wi}
                          ref={active ? activeWordRef : null}
                          onClick={onWordClick}
                          onDoubleClick={(e) => { e.preventDefault(); beginInlineEdit(i, wi, original) }}
                          onContextMenu={(e) => {
                            e.preventDefault()
                            setSelectedWord(selected ? null : key)
                          }}
                          title={
                            deleted ? 'Click to undo delete'
                            : replaced ? `Will be replaced with "${replacedTo}" · Click to undo`
                            : 'Click to delete · Double-click to edit · Shift+click to jump · Right-click for more'
                          }
                          className={`cursor-pointer relative inline-block transition-colors ${
                            deleted
                              ? 'text-red-400 line-through decoration-red-300'
                              : replaced
                              ? 'text-violet-700 bg-violet-50 rounded px-0.5 underline decoration-violet-400 decoration-2 underline-offset-2'
                              : active
                              ? 'bg-accent-100 text-accent-700 rounded'
                              : filler
                              ? 'bg-amber-50 text-amber-700 rounded px-0.5 underline decoration-amber-400 decoration-dotted underline-offset-2'
                              : 'hover:text-accent-600 hover:underline hover:underline-offset-2 hover:decoration-accent-300'
                          } ${selected ? 'ring-1 ring-accent-300 rounded' : ''}`}
                        >
                          {replaced ? replacedTo : original}{' '}
                          {selected && (
                            <span className="absolute -top-8 left-0 z-10 flex items-center gap-1 bg-gray-900 text-white text-xs rounded-lg px-2 py-1 whitespace-nowrap shadow-lg animate-fade-in">
                              <button
                                onClick={(e) => { e.stopPropagation(); player.seek(w.start, { play: true }); setSelectedWord(null) }}
                                className="hover:text-accent-300 transition-colors"
                              >
                                ▶ Jump
                              </button>
                              <span className="text-gray-600">·</span>
                              <button
                                onClick={(e) => { e.stopPropagation(); beginInlineEdit(i, wi, original) }}
                                className="hover:text-violet-300 transition-colors"
                              >
                                ✏️ Edit
                              </button>
                              <span className="text-gray-600">·</span>
                              <button
                                onClick={(e) => { e.stopPropagation(); pending.toggleDelete(i, wi); setSelectedWord(null) }}
                                className="hover:text-red-300 transition-colors"
                              >
                                {deleted ? '↺ Undo' : '🗑️ Delete'}
                              </button>
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
              <p className="text-xs text-gray-400">
                {transcriptState === 'ready'
                  ? `${wordCount} words · ${fmtMMSS(transcript?.duration || player.duration)} runtime`
                  : transcriptState === 'transcribing'
                  ? 'Generating transcript…'
                  : transcriptState === 'no-audio'
                  ? 'No audio yet'
                  : '—'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Modals */}
      {showExport && (
        <ExportModal
          onClose={() => setShowExport(false)}
          projectId={project.id}
          projectName={projectName}
          versions={versions}
          activeVersionId={activeVersionId}
          durationSec={player.duration || transcript?.duration || 0}
          exportHistory={exportHistory}
          onExported={(record) => setExportHistory(prev => [record, ...prev])}
          getToken={getToken}
        />
      )}
      {showCompare && (
        <CompareModal
          onClose={() => setShowCompare(false)}
          onExport={() => setShowExport(true)}
        />
      )}
    </div>
  )
}
