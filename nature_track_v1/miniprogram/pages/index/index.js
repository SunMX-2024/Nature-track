const app = getApp()

const DEFAULT_JOURNALS = [
  'Nature',
  'Nature Geoscience',
  'Nature Climate Change',
  'Nature Communications',
  'Science',
  'Science Advances',
  'One Earth',
  'Global Change Biology',
  'New Phytologist'
]

Page({
  data: {
    apiBase: '',
    filtersOpen: false,
    journals: DEFAULT_JOURNALS,
    selectedJournals: ['Nature', 'Nature Geoscience', 'Nature Communications', 'Science Advances'],
    customJournalText: '',
    keywordText: '',
    keywordPlaceholder: 'forest\necosystem\nclimate change\nNOT crop',
    keywordMatch: 'all',
    keywordScope: 'abstract',
    daysBack: 30,
    daysLabel: '1 month',
    daysMenuOpen: false,
    dayOptions: [
      { label: '1 day', value: 1 },
      { label: '1 week', value: 7 },
      { label: '1 month', value: 30 },
      { label: '1 year', value: 365 },
      { label: '5 year', value: 1825 }
    ],
    maxResults: 100,
    articleTypes: ['article', 'review'],
    loading: false,
    error: '',
    articles: [],
    expanded: {}
  },

  onLoad() {
    this.setData({ apiBase: app.globalData.apiBase })
  },

  toggleFilters() {
    this.setData({ filtersOpen: !this.data.filtersOpen })
  },

  closeFilters() {
    this.setData({ filtersOpen: false, daysMenuOpen: false })
  },

  toggleJournal(event) {
    const journal = event.currentTarget.dataset.journal
    const selected = new Set(this.data.selectedJournals)
    if (selected.has(journal)) {
      selected.delete(journal)
    } else {
      selected.add(journal)
    }
    this.setData({ selectedJournals: Array.from(selected) })
  },

  onCustomJournalInput(event) {
    this.setData({ customJournalText: event.detail.value })
  },

  addCustomJournal() {
    const journal = this.data.customJournalText.trim()
    if (!journal) {
      wx.showToast({ title: 'Enter a journal name', icon: 'none' })
      return
    }

    const journals = Array.from(new Set([...this.data.journals, journal]))
    const selectedJournals = Array.from(new Set([...this.data.selectedJournals, journal]))
    this.setData({
      journals,
      selectedJournals,
      customJournalText: ''
    })
  },

  onKeywordInput(event) {
    this.setData({ keywordText: event.detail.value })
  },

  toggleDaysMenu() {
    this.setData({ daysMenuOpen: !this.data.daysMenuOpen })
  },

  selectDays(event) {
    const daysBack = Number(event.currentTarget.dataset.value)
    const daysLabel = event.currentTarget.dataset.label
    this.setData({
      daysBack,
      daysLabel,
      daysMenuOpen: false
    })
  },

  setMatch(event) {
    this.setData({ keywordMatch: event.currentTarget.dataset.value })
  },

  setScope(event) {
    this.setData({ keywordScope: event.currentTarget.dataset.value })
  },

  search() {
    if (!this.data.selectedJournals.length) {
      wx.showToast({ title: 'Select journals first', icon: 'none' })
      return
    }
    this.setData({ loading: true, error: '', articles: [], expanded: {} })
    wx.request({
      url: `${this.data.apiBase}/search`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: {
        journals: this.data.selectedJournals,
        keywords: this.data.keywordText,
        keyword_match: this.data.keywordMatch,
        keyword_scope: this.data.keywordScope,
        article_types: this.data.articleTypes,
        days_back: this.data.daysBack,
        max_results: this.data.maxResults,
        require_abstract: true,
        research_only: true
      },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          this.setData({ articles: res.data.articles || [] })
        } else {
          this.setData({ error: `API error: ${res.statusCode}` })
        }
      },
      fail: (err) => {
        this.setData({ error: err.errMsg || 'Cannot connect to API' })
      },
      complete: () => {
        this.setData({ loading: false, filtersOpen: false, daysMenuOpen: false })
      }
    })
  },

  toggleAbstract(event) {
    const index = event.currentTarget.dataset.index
    const expanded = { ...this.data.expanded }
    expanded[index] = !expanded[index]
    this.setData({ expanded })
  },

  copyDoi(event) {
    const url = event.currentTarget.dataset.url
    if (!url) return
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: 'DOI link copied', icon: 'none' })
    })
  },

  openDoi(event) {
    const url = event.currentTarget.dataset.url
    if (!url) return
    wx.navigateTo({
      url: `/pages/webview/webview?url=${encodeURIComponent(url)}`
    })
  }
})
