const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

export async function streamChat({ projectId, messages, getToken, onDelta, signal }) {
  const token = await getToken()
  const res = await fetch(`${API_URL}/projects/${projectId}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      messages: messages.map(m => ({
        role: m.role === 'ai' ? 'assistant' : m.role,
        content: m.text ?? m.content ?? '',
      })),
    }),
    signal,
  })

  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`Chat failed (${res.status}): ${detail}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const event of events) {
      const line = event.split('\n').find(l => l.startsWith('data: '))
      if (!line) continue
      try {
        const data = JSON.parse(line.slice(6))
        if (data.error) throw new Error(data.error)
        if (data.delta) onDelta(data.delta)
        if (data.done) return
      } catch (e) {
        if (e instanceof SyntaxError) continue
        throw e
      }
    }
  }
}
