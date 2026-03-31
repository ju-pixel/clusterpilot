const API_URL = import.meta.env.VITE_API_URL || 'https://api.clusterpilot.sh'

export function makeApiClient(getToken) {
  async function req(method, path, body) {
    const token = await getToken()
    const res = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`${res.status}: ${text}`)
    }
    if (res.status === 204) return null
    return res.json()
  }

  return {
    getJobs:           ()      => req('GET',  '/jobs'),
    getMe:             ()      => req('GET',  '/users/me'),
    getKeys:           ()      => req('GET',  '/keys'),
    issueKey:          ()      => req('POST', '/keys'),
    rotateKey:         ()      => req('POST', '/keys/rotate'),
    getNotifyPrefs:    ()      => req('GET',  '/notify/preferences'),
    updateNotifyPrefs: (prefs) => req('PUT',  '/notify/preferences', prefs),
    getBillingPortal:  ()      => req('POST', '/users/me/billing-portal'),
    createCheckout:    ()      => req('POST', '/users/me/checkout'),
  }
}
