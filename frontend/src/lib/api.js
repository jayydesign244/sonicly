const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

async function authHeaders(getToken) {
  const token = getToken ? await getToken() : null
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function handleJson(res) {
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${detail}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export async function listProjects({ getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/`, {
    headers: { ...(await authHeaders(getToken)) },
  })
  return handleJson(res)
}

export async function createProject({ name, duration, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders(getToken)) },
    body: JSON.stringify({ name, ...(duration ? { duration } : {}) }),
  })
  return handleJson(res)
}

export async function deleteProject({ id, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/${id}`, {
    method: 'DELETE',
    headers: { ...(await authHeaders(getToken)) },
  })
  return handleJson(res)
}

export async function uploadAudio({ id, file, getToken } = {}) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_URL}/projects/${id}/upload`, {
    method: 'POST',
    headers: { ...(await authHeaders(getToken)) },
    body: form,
  })
  return handleJson(res)
}

export async function getProject({ id, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/${id}`, {
    headers: { ...(await authHeaders(getToken)) },
  })
  return handleJson(res)
}

export async function getProcessingStatus({ id, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/${id}/processing`, {
    headers: { ...(await authHeaders(getToken)) },
  })
  return handleJson(res)
}

export async function transcribeAudio({ id, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/${id}/transcribe`, {
    method: 'POST',
    headers: { ...(await authHeaders(getToken)) },
  })
  return handleJson(res)
}

export async function cloneVoice({ id, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/${id}/voice/clone`, {
    method: 'POST',
    headers: { ...(await authHeaders(getToken)) },
  })
  return handleJson(res)
}

export async function detectFillers({ id, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/${id}/fillers`, {
    method: 'POST',
    headers: { ...(await authHeaders(getToken)) },
  })
  return handleJson(res)
}

export async function applyEdits({ id, edits, parentVersionId, label, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/${id}/edits/apply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders(getToken)) },
    body: JSON.stringify({
      edits,
      parent_version_id: parentVersionId ?? null,
      label: label ?? null,
    }),
  })
  return handleJson(res)
}

export async function listVersions({ id, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/${id}/versions`, {
    headers: { ...(await authHeaders(getToken)) },
  })
  return handleJson(res)
}

export async function exportProject({ id, format, versionId, filename, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/${id}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders(getToken)) },
    body: JSON.stringify({
      format,
      version_id: versionId ?? null,
      filename: filename ?? null,
    }),
  })
  return handleJson(res)
}

export async function activateVersion({ id, versionId, getToken } = {}) {
  const res = await fetch(`${API_URL}/projects/${id}/versions/${versionId}/activate`, {
    method: 'POST',
    headers: { ...(await authHeaders(getToken)) },
  })
  return handleJson(res)
}

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
