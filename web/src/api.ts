export type Settings = {
  journals: string[]
  keywords: string
  keyword_match: 'all' | 'any'
  keyword_scope: 'abstract' | 'title_abstract' | 'title'
  article_types: string[]
  days_back: number
  max_results: number
  require_abstract: boolean
  research_only: boolean
}

export type Options = {
  journals: string[]
  article_types: string[]
  keyword_match: string[]
  keyword_scope: string[]
  defaults: Settings
}

export type Article = {
  title: string
  journal: string
  doi: string
  doi_url: string
  publication_date: string
  article_type: string
  abstract: string
  authors: string[]
  corresponding_authors: string[]
  is_oa: boolean
  pdf_url: string
  landing_page_url: string
  keyword_hits: number
}

export type SearchResponse = {
  count: number
  candidate_count: number
  query: {
    from_date: string
    to_date: string
    keywords: string
    terms: string[]
    candidate_searches: string[]
    keyword_match: string
    keyword_scope: string
  }
  articles: Article[]
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
    ...init,
  })

  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `Request failed with ${response.status}`)
  }

  return response.json() as Promise<T>
}

export function getOptions() {
  return request<Options>('/options')
}

export function getSettings() {
  return request<{ settings: Settings }>('/settings')
}

export function saveSettings(settings: Settings) {
  return request<{ settings: Settings }>('/settings', {
    method: 'PUT',
    body: JSON.stringify(settings),
  })
}

export function search(settings: Settings) {
  return request<SearchResponse>('/search', {
    method: 'POST',
    body: JSON.stringify(settings),
  })
}
