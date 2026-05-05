import { createContext, useContext, useEffect, useState } from 'react'
import { supabase, isSupabaseConfigured } from '../lib/supabase'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!isSupabaseConfigured()) {
      // Dev mode without Supabase configured — auto-authenticate so the prototype still works
      setSession({ user: { id: 'dev', email: 'dev@local', user_metadata: { name: 'Dev User' } } })
      setLoading(false)
      return
    }

    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setLoading(false)
    })

    const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session)
    })

    return () => listener.subscription.unsubscribe()
  }, [])

  const signInWithProvider = async (provider) => {
    if (!isSupabaseConfigured()) {
      // Dev fallback
      setSession({ user: { id: 'dev', email: 'dev@local' } })
      return { error: null }
    }
    return await supabase.auth.signInWithOAuth({
      provider,
      options: { redirectTo: `${window.location.origin}/dashboard` },
    })
  }

  const signUp = async (email, password, name) => {
    if (!isSupabaseConfigured()) {
      setSession({ user: { id: 'dev', email, user_metadata: { name } } })
      return { error: null }
    }
    return await supabase.auth.signUp({
      email,
      password,
      options: { data: { name } },
    })
  }

  const signIn = async (email, password) => {
    if (!isSupabaseConfigured()) {
      setSession({ user: { id: 'dev', email } })
      return { error: null }
    }
    return await supabase.auth.signInWithPassword({ email, password })
  }

  const signOut = async () => {
    if (!isSupabaseConfigured()) {
      setSession(null)
      return
    }
    await supabase.auth.signOut()
  }

  const value = {
    session,
    user: session?.user || null,
    loading,
    isAuthenticated: Boolean(session),
    signInWithProvider,
    signUp,
    signIn,
    signOut,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
