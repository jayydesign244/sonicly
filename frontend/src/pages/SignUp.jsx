import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const SocialButton = ({ icon, label, onClick, disabled }) => (
  <button
    onClick={onClick}
    disabled={disabled}
    className="w-full flex items-center gap-3 px-4 py-2.5 border border-gray-200 rounded-lg text-sm text-gray-700 hover:bg-gray-50 hover:border-gray-300 transition-colors duration-150 font-medium disabled:opacity-50 disabled:cursor-not-allowed"
  >
    {icon}
    {label}
  </button>
)

export default function SignUp() {
  const navigate = useNavigate()
  const { signUp, signInWithProvider, authReady } = useAuth()

  const [showEmail, setShowEmail] = useState(false)
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [showPass, setShowPass] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const busy = submitting || !authReady

  const handleSocial = async (provider) => {
    setError('')
    setSubmitting(true)
    const { error } = await signInWithProvider(provider)
    if (error) {
      setError(error.message || 'Sign-in failed')
      setSubmitting(false)
    } else {
      navigate('/dashboard')
    }
  }

  const handleEmailSignUp = async () => {
    setError('')
    if (!form.email || !form.password || form.password.length < 8) {
      setError('Email and a password (8+ chars) are required.')
      return
    }
    setSubmitting(true)
    const { error } = await signUp(form.email, form.password, form.name)
    if (error) {
      setError(error.message || 'Sign-up failed')
      setSubmitting(false)
    } else {
      navigate('/dashboard')
    }
  }

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center px-4">
      <div className="w-full max-w-sm animate-slide-up">
        <div className="card p-8 shadow-modal">
          {/* Logo */}
          <div className="flex justify-center mb-6">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-accent-500 rounded-lg flex items-center justify-center">
                <svg width="16" height="16" viewBox="0 0 20 20" fill="white">
                  <rect x="1" y="8" width="2.5" height="4" rx="1.25" />
                  <rect x="5" y="5" width="2.5" height="10" rx="1.25" />
                  <rect x="9" y="3" width="2.5" height="14" rx="1.25" />
                  <rect x="13" y="6" width="2.5" height="8" rx="1.25" />
                  <rect x="17" y="8" width="2.5" height="4" rx="1.25" />
                </svg>
              </div>
              <span className="font-semibold text-gray-900">Sonicly</span>
            </div>
          </div>

          <h1 className="text-xl font-semibold text-gray-900 text-center mb-6">
            Create your account
          </h1>

          {error && (
            <div className="mb-4 px-3 py-2 bg-red-50 border border-red-100 rounded-lg text-xs text-red-600">
              {error}
            </div>
          )}

          <div className="space-y-2.5">
            <SocialButton
              onClick={() => handleSocial('google')}
              disabled={busy}
              label="Continue with Google"
              icon={<GoogleIcon />}
            />
            <SocialButton
              onClick={() => handleSocial('facebook')}
              disabled={busy}
              label="Continue with Facebook"
              icon={<FacebookIcon />}
            />
            <SocialButton
              onClick={() => handleSocial('apple')}
              disabled={busy}
              label="Continue with Apple"
              icon={<AppleIcon />}
            />

            {!showEmail ? (
              <SocialButton
                onClick={() => setShowEmail(true)}
                label="Continue with Email"
                icon={
                  <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                }
              />
            ) : (
              <>
                <div className="flex items-center gap-3 my-1">
                  <div className="flex-1 h-px bg-gray-100" />
                  <span className="text-xs text-gray-400">or</span>
                  <div className="flex-1 h-px bg-gray-100" />
                </div>

                <div className="space-y-3 animate-fade-in">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1.5">Full name</label>
                    <input
                      type="text"
                      placeholder="Alex Johnson"
                      className="input-field"
                      value={form.name}
                      onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1.5">Email address</label>
                    <input
                      type="email"
                      placeholder="you@example.com"
                      className="input-field"
                      value={form.email}
                      onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1.5">Password</label>
                    <div className="relative">
                      <input
                        type={showPass ? 'text' : 'password'}
                        placeholder="Min. 8 characters"
                        className="input-field pr-10"
                        value={form.password}
                        onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                      />
                      <button
                        type="button"
                        onClick={() => setShowPass(v => !v)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                      >
                        {showPass ? <EyeOffIcon /> : <EyeIcon />}
                      </button>
                    </div>
                  </div>

                  <button
                    onClick={handleEmailSignUp}
                    disabled={busy}
                    className="btn-primary w-full py-2.5 text-sm disabled:opacity-50"
                  >
                    {!authReady ? 'Loading…' : submitting ? 'Creating account...' : 'Create account'}
                  </button>
                </div>
              </>
            )}
          </div>

          <div className="mt-5 text-center">
            <p className="text-sm text-gray-500">
              Already have an account?{' '}
              <Link to="/login" className="text-accent-500 hover:text-accent-600 font-medium">
                Log in
              </Link>
            </p>
          </div>

          <p className="mt-4 text-xs text-gray-400 text-center leading-relaxed">
            By signing up you agree to our{' '}
            <a href="#" className="underline underline-offset-2">Terms</a> and{' '}
            <a href="#" className="underline underline-offset-2">Privacy Policy</a>
          </p>
        </div>
      </div>
    </div>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
    </svg>
  )
}

function FacebookIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="#1877F2">
      <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z" />
    </svg>
  )
}

function AppleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="#000">
      <path d="M12.152 6.896c-.948 0-2.415-1.078-3.96-1.04-2.04.027-3.91 1.183-4.961 3.014-2.117 3.675-.546 9.103 1.519 12.09 1.013 1.454 2.208 3.09 3.792 3.039 1.52-.065 2.09-.987 3.935-.987 1.831 0 2.35.987 3.96.948 1.637-.026 2.676-1.48 3.676-2.948 1.156-1.688 1.636-3.325 1.662-3.415-.039-.013-3.182-1.221-3.22-4.857-.026-3.04 2.48-4.494 2.597-4.559-1.429-2.09-3.623-2.324-4.39-2.376-2-.156-3.675 1.09-4.61 1.09zM15.53 3.83c.843-1.012 1.4-2.427 1.245-3.83-1.207.052-2.662.805-3.532 1.818-.78.896-1.454 2.338-1.273 3.714 1.338.104 2.715-.688 3.559-1.701" />
    </svg>
  )
}

function EyeIcon() {
  return (
    <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
    </svg>
  )
}

function EyeOffIcon() {
  return (
    <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
    </svg>
  )
}
