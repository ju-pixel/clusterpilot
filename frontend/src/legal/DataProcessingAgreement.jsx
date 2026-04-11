import LegalPage, { H2, H3, P, UL, Table, A } from './LegalPage'

export default function DataProcessingAgreement() {
  return (
    <LegalPage title="Data Processing Agreement" lastUpdated="April 2026">

      <P>
        This Data Processing Agreement ("<strong>DPA</strong>") supplements the{' '}
        <a href="/terms" style={{ color: '#FFB866' }}>Terms of Service</a> and applies to
        users in the European Economic Area (EEA), the United Kingdom, and Switzerland
        ("<strong>EU Users</strong>"). It is entered into between Frankly Labs
        ("<strong>Processor</strong>") and the EU User ("<strong>Controller</strong>").
      </P>
      <P>
        Where Frankly Labs collects and uses personal data for its own purposes (e.g., billing,
        account management), it acts as a data controller; this DPA addresses the narrower
        scope where Frankly Labs processes personal data on behalf of the Controller.
      </P>
      <P>
        This DPA is incorporated by reference into the Terms of Service and has effect as a
        contract under Article 28 of the General Data Protection Regulation (GDPR).
      </P>

      <H2>1. Definitions</H2>
      <P>
        Terms defined in the GDPR (personal data, processing, data subject, supervisory
        authority) have the same meaning here. "Services" means the ClusterPilot hosted tier
        as described in the Terms of Service.
      </P>

      <H2>2. Subject matter and duration</H2>
      <P>
        The Processor will process personal data on behalf of the Controller for the duration
        of the Controller&apos;s subscription to the hosted tier, and for a period not exceeding
        30 days after termination (to allow for deletion).
      </P>

      <H2>3. Categories of personal data and data subjects</H2>
      <Table
        headers={['Category', 'Examples', 'Data subjects']}
        rows={[
          ['Account identifiers', 'Name, email address', 'Registered users (Controller)'],
          ['Usage metadata', 'Request timestamps, cluster type, token count', 'Registered users (Controller)'],
        ]}
      />
      <P>
        ClusterPilot does not collect or process special categories of personal data
        (Article 9 GDPR). Job scripts submitted through the service may incidentally contain
        personal data if included by the Controller; the Controller is responsible for ensuring
        that any such data is minimised and appropriate to include.
      </P>

      <H2>4. Processor obligations</H2>
      <P>The Processor shall:</P>
      <UL items={[
        'Process personal data only on documented instructions from the Controller (including those set out in these Terms and this DPA), unless required to do otherwise by applicable law.',
        'Ensure that persons authorised to process personal data have committed to confidentiality.',
        'Implement appropriate technical and organisational security measures in accordance with Article 32 GDPR (see section 7).',
        'Not engage sub-processors without the Controller\u2019s prior authorisation (see section 5).',
        'Assist the Controller in responding to data subject rights requests insofar as this is possible given the nature of the processing.',
        'Delete or return all personal data on request at the end of the contract.',
        'Make available to the Controller all information necessary to demonstrate compliance with Article 28 GDPR.',
        'Notify the Controller without undue delay (and in any case within 72 hours of becoming aware) of a personal data breach.',
      ]} />

      <H2>5. Sub-processors</H2>
      <P>
        The Controller provides general authorisation for the Processor to engage the following
        sub-processors. The Processor will notify the Controller of any intended changes
        (additions or replacements) at least 14 days in advance via email, giving the
        Controller an opportunity to object.
      </P>
      <Table
        headers={['Sub-processor', 'Purpose', 'Location', 'DPA / Safeguard']}
        rows={[
          ['Clerk', 'Authentication', 'United States', 'SCCs + DPA'],
          ['Stripe', 'Payment processing', 'United States', 'EU–US DPF + DPA'],
          ['Fly.io', 'Hosting, database', 'United States / EU', 'SCCs + DPA'],
          ['Resend', 'Transactional email', 'United States', 'SCCs + DPA'],
          ['Anthropic', 'AI script generation (content only, no PII stored)', 'United States', 'Privacy policy + data retention policy'],
        ]}
      />
      <P>
        Where sub-processors are located outside the EEA, transfers are covered by Standard
        Contractual Clauses (SCCs) adopted by the European Commission, or the EU–US Data
        Privacy Framework (DPF) where the sub-processor is certified.
      </P>

      <H2>6. Data subject rights</H2>
      <P>
        The Processor will, upon receiving a data subject request that relates to data
        processed under this DPA, promptly notify the Controller and provide reasonable
        assistance in responding to the request within the applicable statutory timeframe.
      </P>
      <P>
        Data subjects may also exercise their rights directly by contacting{' '}
        <A href="mailto:privacy@clusterpilot.sh">privacy@clusterpilot.sh</A>.
      </P>

      <H2>7. Technical and organisational measures</H2>
      <UL items={[
        'Encryption in transit: TLS 1.2 or higher for all data in transit.',
        'Encryption at rest: AES-256 for all data stored on Fly.io.',
        'Access control: production access restricted to named individuals; multi-factor authentication required.',
        'Audit logging: all administrative access to production systems is logged.',
        'Vulnerability management: dependencies are reviewed and updated on a regular basis.',
        'Incident response: a documented procedure is in place for detecting, reporting, and managing security incidents.',
      ]} />

      <H2>8. Data transfers outside the EEA</H2>
      <P>
        Where personal data is transferred to a country outside the EEA that does not
        benefit from an adequacy decision, the transfer is subject to Standard Contractual
        Clauses (Commission Implementing Decision (EU) 2021/914) or another lawful transfer
        mechanism. Copies of applicable SCCs are available on request.
      </P>

      <H2>9. Data breach notification</H2>
      <P>
        In the event of a personal data breach affecting data processed under this DPA,
        the Processor will notify the Controller without undue delay and in any event
        within 72 hours of becoming aware of the breach. The notification will include,
        to the extent known: the nature of the breach, the categories and approximate
        number of data subjects affected, the likely consequences, and the measures taken
        or proposed to address the breach.
      </P>

      <H2>10. Return and deletion of data</H2>
      <P>
        On termination of the Services, the Processor will, at the Controller&apos;s choice,
        return or delete all personal data within 30 days. Deletion is permanent and
        irreversible. Billing records may be retained beyond this period where required
        by applicable law.
      </P>

      <H2>11. Audits</H2>
      <P>
        The Controller may request an audit of the Processor's data processing activities,
        provided it gives at least 30 days' advance written notice, the audit occurs during
        normal business hours, and the costs of the audit are borne by the Controller.
        The parties will agree on reasonable scope and format before the audit begins.
      </P>

      <H2>12. Liability</H2>
      <P>
        Each party's liability under this DPA is subject to the limitations set out in the
        Terms of Service. Where the GDPR mandates a higher standard of liability, that
        standard applies to the extent required by law.
      </P>

      <H2>13. Governing law</H2>
      <P>
        This DPA is governed by the law applicable to the main Terms of Service. Notwithstanding
        this, obligations imposed directly by GDPR are governed by the law of the applicable
        EU Member State.
      </P>

      <H2>Contact</H2>
      <P>
        For data protection enquiries:<br />
        <A href="mailto:privacy@clusterpilot.sh">privacy@clusterpilot.sh</A><br />
        Frankly Labs, Canada
      </P>
    </LegalPage>
  )
}
