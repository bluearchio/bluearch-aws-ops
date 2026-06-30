import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { RecommendationNote, RecommendationResponse } from '@/types/api'

export const useRecommendationsStore = defineStore('recommendations', () => {
  const items = ref<RecommendationResponse[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const filters = ref({
    recommendation_type: '',
    account_id: '',
    region: '',
    page: 1,
    page_size: 50,
  })

  async function fetchItems() {
    loading.value = true
    error.value = null
    try {
      const params: Record<string, string> = {
        page: String(filters.value.page),
        page_size: String(filters.value.page_size),
      }
      if (filters.value.recommendation_type) params.recommendation_type = filters.value.recommendation_type
      if (filters.value.account_id) params.account_id = filters.value.account_id
      if (filters.value.region) params.region = filters.value.region

      const data = await api.listRecommendations(params)
      items.value = data.items
      total.value = data.total
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load recommendations'
    } finally {
      loading.value = false
    }
  }

  async function fetchTypes() {
    return api.recommendationTypes()
  }

  // --- Notes CRUD (kept in-store so every view shares a single source of
  // truth for notes attached to a recommendation row). -------------------

  function _rec(id: string): RecommendationResponse | undefined {
    return items.value.find((r) => r.id === id)
  }

  async function addNote(recId: string, body: string, author?: string): Promise<RecommendationNote> {
    const note = await api.createRecommendationNote(recId, body, author)
    const rec = _rec(recId)
    if (rec) rec.notes = [note, ...(rec.notes || [])]
    return note
  }

  async function updateNote(recId: string, noteId: string, body: string): Promise<RecommendationNote> {
    const updated = await api.updateRecommendationNote(noteId, body)
    const rec = _rec(recId)
    if (rec && rec.notes) {
      const idx = rec.notes.findIndex((n) => n.id === noteId)
      if (idx !== -1) rec.notes[idx] = updated
    }
    return updated
  }

  async function deleteNote(recId: string, noteId: string): Promise<void> {
    await api.deleteRecommendationNote(noteId)
    const rec = _rec(recId)
    if (rec && rec.notes) {
      rec.notes = rec.notes.filter((n) => n.id !== noteId)
    }
  }

  return {
    items, total, loading, error, filters,
    fetchItems, fetchTypes,
    addNote, updateNote, deleteNote,
  }
})
