import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import LandingPage from '../LandingPage'
import BlogPage from './blog/BlogPage'
import Support from './Support'
import PrivacyPolicy from './legal/PrivacyPolicy'
import TermsOfService from './legal/TermsOfService'
import DataProcessingAgreement from './legal/DataProcessingAgreement'
import AcceptableUsePolicy from './legal/AcceptableUsePolicy'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/blog" element={<BlogPage />} />
        <Route path="/blog/:slug" element={<BlogPage />} />
        <Route path="/support" element={<Support />} />
        <Route path="/privacy" element={<PrivacyPolicy />} />
        <Route path="/terms" element={<TermsOfService />} />
        <Route path="/dpa" element={<DataProcessingAgreement />} />
        <Route path="/acceptable-use" element={<AcceptableUsePolicy />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)
