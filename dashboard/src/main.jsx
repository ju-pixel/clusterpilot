import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ClerkProvider } from '@clerk/react'
import './index.css'
import App from './App.jsx'

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

if (!publishableKey) {
  throw new Error('Missing VITE_CLERK_PUBLISHABLE_KEY in .env')
}

// Match ClusterPilot dark theme
const clerkAppearance = {
  variables: {
    colorBackground:       '#0d0d0d',
    colorInputBackground:  '#111111',
    colorInputText:        '#fafafa',
    colorPrimary:          '#FFB866',
    colorText:             '#fafafa',
    colorTextSecondary:    '#8899b2',
    colorNeutral:          '#fafafa',
    borderRadius:          '6px',
    fontFamily:            "'DM Sans', system-ui, sans-serif",
  },
  elements: {
    card:            { boxShadow: 'none', border: '1px solid #222222' },
    formButtonPrimary: { backgroundColor: '#FFB866', color: '#0a0a0a' },
  },
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ClerkProvider publishableKey={publishableKey} appearance={clerkAppearance}>
      <App />
    </ClerkProvider>
  </StrictMode>,
)
