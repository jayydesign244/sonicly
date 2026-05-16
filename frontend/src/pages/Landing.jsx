import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Waveform from '../components/Waveform'
import { useAuth } from '../context/AuthContext'

const features = [
  {
    icon: (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
    title: 'AI-Powered Cleanup',
    desc: 'Remove background noise, echo, and hiss automatically in seconds.',
  },
  {
    icon: (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-3 3-3-3z" />
      </svg>
    ),
    title: 'Edit by Typing',
    desc: 'Click any word in the transcript and change it — the audio updates instantly.',
  },
  {
    icon: (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
      </svg>
    ),
    title: 'Before / After Compare',
    desc: 'Hear exactly what changed. Switch between versions with one click.',
  },
  {
    icon: (
      <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
      </svg>
    ),
    title: 'Export Any Format',
    desc: 'Download as MP3, WAV, or M4A — no watermarks, no subscriptions to start.',
  },
]

export default function Landing() {
  const navigate = useNavigate()
  const { isAuthenticated, user, signOut } = useAuth()

  return (
    <div className="min-h-screen bg-white flex flex-col">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-gray-100 bg-white/90 backdrop-blur-sm">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="hover:opacity-80 transition-opacity" aria-label="Go to home">
            <Logo />
          </button>
          <div className="flex items-center gap-3">
            {isAuthenticated ? (
              <>
                <button
                  onClick={() => navigate('/dashboard')}
                  className="btn-ghost text-sm"
                >
                  Dashboard
                </button>
                <UserMenu user={user} onSignOut={async () => { await signOut(); navigate('/') }} />
              </>
            ) : (
              <>
                <button
                  onClick={() => navigate('/login')}
                  className="btn-ghost text-sm"
                >
                  Log in
                </button>
                <button
                  onClick={() => navigate('/signup')}
                  className="btn-primary"
                >
                  Start for free
                </button>
              </>
            )}
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="flex-1 flex flex-col items-center justify-center text-center px-6 pt-32 pb-24">
        <div className="inline-flex items-center gap-2 bg-accent-50 text-accent-600 text-xs font-medium px-3 py-1.5 rounded-full border border-accent-100 mb-8 animate-fade-in">
          <span className="w-1.5 h-1.5 bg-accent-500 rounded-full"></span>
          AI audio editing, finally simple
        </div>

        <h1 className="text-5xl md:text-6xl font-serif italic text-gray-900 leading-tight max-w-2xl mb-5 animate-slide-up">
          Your audio,{' '}
          <span className="not-italic font-sans font-semibold text-accent-500">exactly</span>{' '}
          how you want it to sound.
        </h1>

        <p className="text-lg text-gray-500 max-w-md mb-10 animate-slide-up" style={{ animationDelay: '0.1s' }}>
          Describe the changes in plain English. Sonicly handles the rest — noise removal, filler words, voice warmth, and more.
        </p>

        <div className="flex items-center gap-3 animate-slide-up" style={{ animationDelay: '0.15s' }}>
          <button
            onClick={() => navigate('/signup')}
            className="btn-primary px-6 py-2.5 text-sm"
          >
            Start for free
          </button>
          <button
            onClick={() => document.getElementById('demo')?.scrollIntoView({ behavior: 'smooth' })}
            className="btn-ghost px-6 py-2.5 text-sm"
          >
            See how it works
          </button>
        </div>

        <p className="mt-5 text-xs text-gray-400 animate-fade-in" style={{ animationDelay: '0.3s' }}>
          No credit card required · Works in your browser
        </p>
      </section>

      {/* Features */}
      <section className="border-t border-gray-100 bg-surface py-16 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            {features.map((f, i) => (
              <div key={i} className="flex flex-col gap-3">
                <div className="w-9 h-9 bg-accent-50 text-accent-500 rounded-lg flex items-center justify-center">
                  {f.icon}
                </div>
                <div>
                  <div className="text-sm font-semibold text-gray-900 mb-1">{f.title}</div>
                  <div className="text-sm text-gray-500 leading-relaxed">{f.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Before / After Demo */}
      <section id="demo" className="py-20 px-6 bg-white">
        <div className="max-w-2xl mx-auto">
          <div className="text-center mb-10">
            <div className="text-xs font-medium text-accent-500 uppercase tracking-wider mb-2">Live Demo</div>
            <h2 className="text-2xl font-semibold text-gray-900">Hear the difference</h2>
            <p className="text-sm text-gray-500 mt-2">Same recording. 12 seconds of AI processing.</p>
          </div>

          <div className="card p-6 space-y-4">
            {/* Before */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">Before</span>
                <span className="text-xs text-gray-400">3:42</span>
              </div>
              <div className="flex items-center gap-3">
                <button className="w-8 h-8 border border-gray-200 rounded-full flex items-center justify-center text-gray-500 hover:border-gray-300 hover:bg-gray-50 transition-colors flex-shrink-0">
                  <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor">
                    <path d="M0 0l10 6-10 6z" />
                  </svg>
                </button>
                <div className="flex-1">
                  <Waveform seed={99} muted height={40} bars={80} />
                </div>
              </div>
            </div>

            <div className="border-t border-gray-100" />

            {/* After */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-accent-500 uppercase tracking-wider">After</span>
                <span className="text-xs text-gray-400">3:42</span>
              </div>
              <div className="flex items-center gap-3">
                <button className="w-8 h-8 bg-accent-500 hover:bg-accent-600 rounded-full flex items-center justify-center text-white transition-colors flex-shrink-0">
                  <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor">
                    <path d="M0 0l10 6-10 6z" />
                  </svg>
                </button>
                <div className="flex-1">
                  <Waveform seed={99} height={40} bars={80} />
                </div>
              </div>
            </div>

            <div className="pt-2 border-t border-gray-100 flex flex-wrap gap-2">
              {['✓ Removed 14dB noise', '✓ Reduced reverb 40%', '✓ Cut 34 filler words', '↑ Quality: 42 → 87'].map((chip) => (
                <span key={chip} className="text-xs text-gray-500 bg-gray-50 border border-gray-100 px-2.5 py-1 rounded-full">
                  {chip}
                </span>
              ))}
            </div>
          </div>

          <div className="text-center mt-8">
            <button onClick={() => navigate('/signup')} className="btn-primary px-8 py-3">
              Try it on your audio →
            </button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-100 py-6 px-6">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <span className="text-xs text-gray-400">© 2026 Sonicly</span>
          <div className="flex items-center gap-5">
            <a href="#" className="text-xs text-gray-400 hover:text-gray-600 transition-colors">Privacy</a>
            <a href="#" className="text-xs text-gray-400 hover:text-gray-600 transition-colors">Terms</a>
          </div>
        </div>
      </footer>
    </div>
  )
}

function UserMenu({ user, onSignOut }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  const name = user?.user_metadata?.name || user?.email?.split('@')[0] || 'You'
  const initials = name.split(' ').map(s => s[0]).slice(0, 2).join('').toUpperCase()

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-2 pl-1 pr-2 py-1 rounded-full border border-gray-200 hover:border-gray-300 hover:bg-gray-50 transition-colors"
      >
        {user?.imageUrl ? (
          <img src={user.imageUrl} alt={name} className="w-7 h-7 rounded-full object-cover" />
        ) : (
          <div className="w-7 h-7 bg-accent-100 text-accent-600 rounded-full flex items-center justify-center text-xs font-semibold">
            {initials}
          </div>
        )}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="text-gray-400">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-12 z-50 card shadow-modal w-60 py-1.5 animate-fade-in">
          <div className="px-3 py-2.5 border-b border-gray-100">
            <div className="flex items-center gap-2.5">
              {user?.imageUrl ? (
                <img src={user.imageUrl} alt={name} className="w-9 h-9 rounded-full object-cover" />
              ) : (
                <div className="w-9 h-9 bg-accent-100 text-accent-600 rounded-full flex items-center justify-center text-sm font-semibold">
                  {initials}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-gray-900 truncate">{name}</div>
                {user?.email && (
                  <div className="text-xs text-gray-400 truncate">{user.email}</div>
                )}
              </div>
            </div>
          </div>

          {[
            {
              label: 'Dashboard',
              onClick: () => { setOpen(false); navigate('/dashboard') },
              icon: (
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
              ),
            },
            {
              label: 'Edit profile',
              onClick: () => {
                setOpen(false)
                if (typeof window !== 'undefined' && window.Clerk?.openUserProfile) {
                  window.Clerk.openUserProfile()
                }
              },
              icon: (
                <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              ),
            },
            {
              label: 'Account settings',
              onClick: () => {
                setOpen(false)
                if (typeof window !== 'undefined' && window.Clerk?.openUserProfile) {
                  window.Clerk.openUserProfile()
                }
              },
              icon: (
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065zM15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              ),
            },
          ].map(({ label, onClick, icon }) => (
            <button
              key={label}
              onClick={onClick}
              className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
                {icon}
              </svg>
              {label}
            </button>
          ))}

          <div className="border-t border-gray-100 my-1" />

          <button
            onClick={() => { setOpen(false); onSignOut() }}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

function Logo() {
  return (
    <div className="flex items-center gap-2">
      <div className="w-7 h-7 bg-accent-500 rounded-md flex items-center justify-center">
        <svg width="14" height="14" viewBox="0 0 20 20" fill="white">
          <rect x="1" y="8" width="2.5" height="4" rx="1.25" />
          <rect x="5" y="5" width="2.5" height="10" rx="1.25" />
          <rect x="9" y="3" width="2.5" height="14" rx="1.25" />
          <rect x="13" y="6" width="2.5" height="8" rx="1.25" />
          <rect x="17" y="8" width="2.5" height="4" rx="1.25" />
        </svg>
      </div>
      <span className="font-semibold text-gray-900 text-sm tracking-tight">Sonicly</span>
    </div>
  )
}
