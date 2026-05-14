import { useCallback, useMemo, useState } from 'react'

/**
 * Local edit queue for transcript-driven editing.
 *
 * Edits live client-side until "Confirm" sends them to the backend.
 * Undo pops the most recently added edit; cancel clears all.
 *
 * Edit shape:
 *   { id, type: 'delete' | 'replace', segment_idx, word_idx, new_text? }
 */
export function usePendingEdits() {
  const [edits, setEdits] = useState([])

  const deletedKeys = useMemo(
    () => new Set(edits.filter(e => e.type === 'delete').map(e => `${e.segment_idx}-${e.word_idx}`)),
    [edits],
  )
  const replacedMap = useMemo(() => {
    const m = new Map()
    for (const e of edits) {
      if (e.type === 'replace') m.set(`${e.segment_idx}-${e.word_idx}`, e.new_text)
    }
    return m
  }, [edits])

  const isDeleted = useCallback((si, wi) => deletedKeys.has(`${si}-${wi}`), [deletedKeys])
  const replacedText = useCallback((si, wi) => replacedMap.get(`${si}-${wi}`), [replacedMap])

  const toggleDelete = useCallback((segment_idx, word_idx) => {
    const key = `${segment_idx}-${word_idx}`
    setEdits(prev => {
      const existingIdx = prev.findIndex(
        e => e.type === 'delete' && `${e.segment_idx}-${e.word_idx}` === key,
      )
      if (existingIdx !== -1) {
        const next = prev.slice()
        next.splice(existingIdx, 1)
        return next
      }
      // If there's a replace on this word, drop it — a delete supersedes.
      const filtered = prev.filter(
        e => !(e.type === 'replace' && `${e.segment_idx}-${e.word_idx}` === key),
      )
      return [
        ...filtered,
        { id: cryptoId(), type: 'delete', segment_idx, word_idx },
      ]
    })
  }, [])

  const queueDeletes = useCallback((refs) => {
    setEdits(prev => {
      const existing = new Set(
        prev
          .filter(e => e.type === 'delete')
          .map(e => `${e.segment_idx}-${e.word_idx}`),
      )
      const additions = refs
        .filter(r => !existing.has(`${r.segment_idx}-${r.word_idx}`))
        .map(r => ({
          id: cryptoId(),
          type: 'delete',
          segment_idx: r.segment_idx,
          word_idx: r.word_idx,
        }))
      return [...prev, ...additions]
    })
  }, [])

  const queueReplace = useCallback((segment_idx, word_idx, new_text) => {
    setEdits(prev => {
      const key = `${segment_idx}-${word_idx}`
      const filtered = prev.filter(
        e => `${e.segment_idx}-${e.word_idx}` !== key,
      )
      return [
        ...filtered,
        { id: cryptoId(), type: 'replace', segment_idx, word_idx, new_text },
      ]
    })
  }, [])

  const undo = useCallback(() => {
    setEdits(prev => prev.slice(0, -1))
  }, [])

  const clear = useCallback(() => setEdits([]), [])

  const serialize = useCallback(() => {
    // Group deletes into a single edit operation per backend contract.
    const deletes = edits
      .filter(e => e.type === 'delete')
      .map(({ segment_idx, word_idx }) => ({ segment_idx, word_idx }))
    const replaces = edits
      .filter(e => e.type === 'replace')
      .map(({ segment_idx, word_idx, new_text }) => ({
        type: 'replace',
        word: { segment_idx, word_idx },
        new_text,
      }))
    const out = []
    if (deletes.length) out.push({ type: 'delete', words: deletes })
    out.push(...replaces)
    return out
  }, [edits])

  return {
    edits,
    count: edits.length,
    deleteCount: edits.filter(e => e.type === 'delete').length,
    replaceCount: edits.filter(e => e.type === 'replace').length,
    isDeleted,
    replacedText,
    toggleDelete,
    queueDeletes,
    queueReplace,
    undo,
    clear,
    serialize,
  }
}

function cryptoId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}
