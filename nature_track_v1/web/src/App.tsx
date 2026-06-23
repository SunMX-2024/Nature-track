import { useEffect, useMemo, useState } from 'react'
import { Archive, ExternalLink, FileDown, Radar, RefreshCcw, Save, Search } from 'lucide-react'
import type { Article, Options, SearchResponse, Settings } from './api'
import { getOptions, getSettings, saveSettings, search } from './api'

const fallbackSettings: Settings = {
  journals: [],
  keywords: '',
  keyword_match: 'any',
  keyword_scope: 'abstract',
  article_types: ['article', 'review'],
  days_back: 365,
  max_results: 50,
  require_abstract: true,
  research_only: true,
}

export function App() {
  const [options, setOptions] = useState<Options | null>(null)
  const [settings, setSettings] = useState<Settings>(fallbackSettings)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    Promise.all([getOptions(), getSettings()])
      .then(([nextOptions, saved]) => {
        if (!active) return
        setOptions(nextOptions)
        setSettings({ ...nextOptions.defaults, ...saved.settings })
      })
      .catch((cause: Error) => setError(cause.message))
    return () => {
      active = false
    }
  }, [])

  const terms = useMemo(
    () => settings.keywords.split(/\n|,|;/).map((item) => item.trim()).filter(Boolean),
    [settings.keywords],
  )

  async function runSearch() {
    setLoading(true)
    setError('')
    try {
      const response = await search(settings)
      setResult(response)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  async function persistSettings() {
    setSaving(true)
    setError('')
    try {
      const response = await saveSettings(settings)
      setSettings(response.settings)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="app-shell">
      <aside className="filter-rail" aria-label="Search filters">
        <div className="brand-lockup">
          <span className="brand-mark"><Radar size={18} /></span>
          <div>
            <h1>Nature-track</h1>
            <p>Literature radar</p>
          </div>
        </div>

        <section className="control-section">
          <div className="section-title">Watched Journals</div>
          <select
            multiple
            value={settings.journals}
            onChange={(event) => {
              const journals = Array.from(event.currentTarget.selectedOptions).map((option) => option.value)
              setSettings((current) => ({ ...current, journals }))
            }}
          >
            {(options?.journals ?? []).map((journal) => (
              <option key={journal} value={journal}>{journal}</option>
            ))}
          </select>
        </section>

        <section className="control-section">
          <div className="section-title">Signal Terms</div>
          <textarea
            value={settings.keywords}
            onChange={(event) => setSettings((current) => ({ ...current, keywords: event.target.value }))}
            placeholder="forest&#10;protected areas&#10;NOT crop"
            rows={8}
          />
          <div className="term-strip" aria-label="Current terms">
            {terms.slice(0, 8).map((term) => <span key={term}>{term}</span>)}
          </div>
        </section>

        <section className="control-section compact-grid">
          <label>
            Window
            <input
              type="number"
              min={1}
              max={3650}
              value={settings.days_back}
              onChange={(event) => setSettings((current) => ({ ...current, days_back: Number(event.target.value) }))}
            />
          </label>
          <label>
            Max
            <input
              type="number"
              min={1}
              max={200}
              value={settings.max_results}
              onChange={(event) => setSettings((current) => ({ ...current, max_results: Number(event.target.value) }))}
            />
          </label>
        </section>

        <section className="control-section two-col">
          <label>
            Match
            <select
              value={settings.keyword_match}
              onChange={(event) => setSettings((current) => ({ ...current, keyword_match: event.target.value as Settings['keyword_match'] }))}
            >
              <option value="any">Any concept</option>
              <option value="all">All concepts</option>
            </select>
          </label>
          <label>
            Field
            <select
              value={settings.keyword_scope}
              onChange={(event) => setSettings((current) => ({ ...current, keyword_scope: event.target.value as Settings['keyword_scope'] }))}
            >
              <option value="abstract">Abstract</option>
              <option value="title_abstract">Title + abstract</option>
              <option value="title">Title</option>
            </select>
          </label>
        </section>

        <section className="control-section checks">
          <label><input type="checkbox" checked={settings.require_abstract} onChange={(event) => setSettings((current) => ({ ...current, require_abstract: event.target.checked }))} /> Require abstract</label>
          <label><input type="checkbox" checked={settings.research_only} onChange={(event) => setSettings((current) => ({ ...current, research_only: event.target.checked }))} /> Research only</label>
        </section>

        <div className="rail-actions">
          <button type="button" className="secondary-action" onClick={persistSettings} disabled={saving}>
            <Save size={16} /> {saving ? 'Saving' : 'Save'}
          </button>
          <button type="button" className="primary-action" onClick={runSearch} disabled={loading}>
            <RefreshCcw size={16} /> {loading ? 'Searching' : 'Search'}
          </button>
        </div>
      </aside>

      <section className="workspace">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">Local research cockpit</p>
            <h2>Scan new Earth and environmental science papers</h2>
          </div>
          <div className="status-pill">
            <Search size={16} />
            {result ? `${result.count} matches from ${result.candidate_count} candidates` : 'Ready'}
          </div>
        </header>

        {error && <div className="error-banner" role="alert">{error}</div>}

        <section className="signal-grid" aria-label="Search summary">
          <Summary label="Window" value={result ? `${result.query.from_date} to ${result.query.to_date}` : `${settings.days_back} days`} />
          <Summary label="Terms" value={terms.length ? terms.slice(0, 3).join(', ') + (terms.length > 3 ? ` +${terms.length - 3}` : '') : 'No keyword filter'} />
          <Summary label="Sources" value={`${settings.journals.length} journals`} />
          <Summary label="Mode" value={`${settings.keyword_match} / ${settings.keyword_scope.replace('_', ' + ')}`} />
        </section>

        <section className="results-panel">
          <div className="panel-heading">
            <div>
              <h3>Matching papers</h3>
              <p>{result ? 'Sorted by publication date and local keyword score.' : 'Run a search to load candidate papers from OpenAlex.'}</p>
            </div>
            <Archive size={18} />
          </div>

          {!result && !loading && <EmptyState />}
          {loading && <LoadingList />}
          {result && result.articles.length === 0 && <NoResults />}
          {result && result.articles.map((paper) => <ArticleRow key={`${paper.doi}-${paper.title}`} paper={paper} />)}
        </section>
      </section>
    </main>
  )
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="summary-cell">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function ArticleRow({ paper }: { paper: Article }) {
  return (
    <article className="article-row">
      <div className="article-score" aria-label={`${paper.keyword_hits} keyword hits`}>
        <strong>{paper.keyword_hits}</strong>
        <span>hits</span>
      </div>
      <div className="article-body">
        <div className="article-meta">
          <span>{paper.journal}</span>
          <span>{paper.publication_date}</span>
          <span>{paper.article_type}</span>
          {paper.is_oa && <span>OA</span>}
        </div>
        <h4>{paper.title}</h4>
        <p>{paper.abstract || 'No abstract available from OpenAlex.'}</p>
        <div className="article-links">
          {paper.doi_url && <a href={paper.doi_url} target="_blank" rel="noreferrer"><ExternalLink size={14} /> DOI</a>}
          {paper.pdf_url && <a href={paper.pdf_url} target="_blank" rel="noreferrer"><FileDown size={14} /> PDF</a>}
        </div>
      </div>
    </article>
  )
}

function EmptyState() {
  return (
    <div className="empty-state">
      <Radar size={28} />
      <h3>No scan has run yet</h3>
      <p>Choose journals and signal terms, then search the OpenAlex feed.</p>
    </div>
  )
}

function NoResults() {
  return (
    <div className="empty-state">
      <Search size={28} />
      <h3>No matching papers</h3>
      <p>Try Any concept, a wider window, or Title + abstract search.</p>
    </div>
  )
}

function LoadingList() {
  return (
    <div className="loading-list" aria-busy="true" aria-label="Loading papers">
      {Array.from({ length: 5 }).map((_, index) => <span key={index} />)}
    </div>
  )
}
