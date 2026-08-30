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
    colorBackground:       '#1D1913',
    colorInputBackground:  '#26211A',
    colorInputText:        '#F2EBDD',
    colorPrimary:          '#e8a020',
    colorText:             '#F2EBDD',
    colorTextSecondary:    '#C9BEA9',
    colorNeutral:          '#F2EBDD',
    borderRadius:          '6px',
    fontFamily:            "'DM Sans', system-ui, sans-serif",
  },
  elements: {
    card:            { boxShadow: 'none', border: '1px solid #4A4235' },
    formButtonPrimary: { backgroundColor: '#e8a020', color: '#14110B' },
  },
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ClerkProvider publishableKey={publishableKey} appearance={clerkAppearance}>
      <App />
    </ClerkProvider>
  </StrictMode>,
)
