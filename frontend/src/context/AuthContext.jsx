import { createContext, useContext } from 'react'
import {
  ClerkProvider,
  useUser,
  useClerk,
  useSignIn,
  useSignUp,
  useAuth as useClerkAuth,
} from '@clerk/clerk-react'

const AuthContext = createContext(null)

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

export const isClerkConfigured = () => Boolean(PUBLISHABLE_KEY)

const clerkErr = (err, fallback) => ({
  message:
    err?.errors?.[0]?.longMessage ||
    err?.errors?.[0]?.message ||
    err?.message ||
    fallback,
})

function shapeUser(user) {
  if (!user) return null
  return {
    id: user.id,
    email: user.primaryEmailAddress?.emailAddress || null,
    imageUrl: user.imageUrl || null,
    user_metadata: {
      name:
        user.fullName ||
        [user.firstName, user.lastName].filter(Boolean).join(' ') ||
        null,
    },
  }
}

function ClerkAuthBridge({ children }) {
  const { isLoaded, isSignedIn, user } = useUser()
  const { signOut: clerkSignOut } = useClerk()
  const { signIn: clerkSignIn, setActive: setSignInActive, isLoaded: signInLoaded } = useSignIn()
  const { signUp: clerkSignUp, setActive: setSignUpActive, isLoaded: signUpLoaded } = useSignUp()
  const { getToken } = useClerkAuth()

  const signInWithProvider = async (provider) => {
    if (!signInLoaded) return { error: { message: 'Auth still loading…' } }
    try {
      await clerkSignIn.authenticateWithRedirect({
        strategy: `oauth_${provider}`,
        redirectUrl: `${window.location.origin}/sso-callback`,
        redirectUrlComplete: `${window.location.origin}/dashboard`,
      })
      return { error: null }
    } catch (err) {
      return { error: clerkErr(err, 'Social sign-in failed') }
    }
  }

  const signIn = async (email, password) => {
    if (!signInLoaded) return { error: { message: 'Auth still loading…' } }
    try {
      const result = await clerkSignIn.create({ identifier: email, password })
      if (result.status === 'complete') {
        await setSignInActive({ session: result.createdSessionId })
        return { error: null }
      }
      return { error: { message: `Additional verification required (${result.status}).` } }
    } catch (err) {
      return { error: clerkErr(err, 'Sign-in failed') }
    }
  }

  const signUp = async (email, password, name) => {
    if (!signUpLoaded) return { error: { message: 'Auth still loading…' } }
    try {
      const [firstName, ...rest] = (name || '').trim().split(/\s+/)
      const result = await clerkSignUp.create({
        emailAddress: email,
        password,
        ...(firstName ? { firstName } : {}),
        ...(rest.length ? { lastName: rest.join(' ') } : {}),
      })
      if (result.status === 'complete') {
        await setSignUpActive({ session: result.createdSessionId })
        return { error: null }
      }
      return {
        error: {
          message:
            'Email verification is required by your Clerk instance. Disable "Email verification" in the Clerk dashboard for this dev flow, or use social login.',
        },
      }
    } catch (err) {
      return { error: clerkErr(err, 'Sign-up failed') }
    }
  }

  const signOut = async () => {
    await clerkSignOut()
  }

  const authReady = isLoaded && signInLoaded && signUpLoaded

  const value = {
    user: shapeUser(user),
    session: isSignedIn ? { user: shapeUser(user) } : null,
    loading: !isLoaded,
    authReady,
    isAuthenticated: Boolean(isSignedIn),
    signInWithProvider,
    signUp,
    signIn,
    signOut,
    getToken,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

function DevAuthProvider({ children }) {
  const value = {
    user: { id: 'dev', email: 'dev@local', user_metadata: { name: 'Dev User' } },
    session: { user: { id: 'dev', email: 'dev@local', user_metadata: { name: 'Dev User' } } },
    loading: false,
    authReady: true,
    isAuthenticated: true,
    signInWithProvider: async () => ({ error: null }),
    signUp: async () => ({ error: null }),
    signIn: async () => ({ error: null }),
    signOut: async () => {},
    getToken: async () => null,
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function AuthProvider({ children }) {
  if (!isClerkConfigured()) {
    if (typeof window !== 'undefined') {
      // eslint-disable-next-line no-console
      console.warn(
        '⚠️  VITE_CLERK_PUBLISHABLE_KEY missing — running in dev auto-auth mode. See SETUP.md.'
      )
    }
    return <DevAuthProvider>{children}</DevAuthProvider>
  }
  return (
    <ClerkProvider
      publishableKey={PUBLISHABLE_KEY}
      signInFallbackRedirectUrl="/dashboard"
      signUpFallbackRedirectUrl="/dashboard"
      signInUrl="/login"
      signUpUrl="/signup"
    >
      <ClerkAuthBridge>{children}</ClerkAuthBridge>
    </ClerkProvider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
