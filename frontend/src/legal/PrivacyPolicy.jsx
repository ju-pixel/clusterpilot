import LegalPage, { H2, H3, P, UL, Table, A } from './LegalPage'

export default function PrivacyPolicy() {
  return (
    <LegalPage title="Privacy Policy" lastUpdated="April 2026">

      <P>
        Frankly Labs ("<strong>we</strong>", "<strong>us</strong>", "<strong>our</strong>") operates
        ClusterPilot at <A href="https://clusterpilot.sh">clusterpilot.sh</A>. This policy explains
        what personal data we collect, why we collect it, how we use it, and what rights you have
        over it. If you use the self-hosted version of ClusterPilot only, this policy does not apply
        to you — we receive no data in that case.
      </P>

      <H2>1. Who we are</H2>
      <P>
        Frankly Labs is a Canadian business (GST: [GST NUMBER]). For questions about this policy,
        contact us at <A href="mailto:privacy@clusterpilot.sh">privacy@clusterpilot.sh</A>.
      </P>

      <H2>2. What data we collect and why</H2>

      <H3>Account data</H3>
      <P>
        When you sign up for the hosted tier, we collect your name and email address via Clerk
        (our authentication provider). This is necessary to create and manage your account.
      </P>

      <H3>Billing data</H3>
      <P>
        Payment processing is handled entirely by Stripe. We do not store your card number, expiry
        date, or CVV. We retain only what Stripe provides after a successful transaction: a
        subscription status, the last four digits of your card (for display purposes), and a
        Stripe customer ID.
      </P>

      <H3>Usage data</H3>
      <P>
        When you use the hosted tier's AI script generation endpoint, we log the request timestamp,
        cluster type, and approximate token count. We do not store the content of your SLURM scripts
        or the description you provide beyond what is needed to complete the request. Job scripts
        are passed to the AI model and then discarded; they are not written to a persistent store.
      </P>

      <H3>Email communications</H3>
      <P>
        We use Resend to send transactional emails (account confirmation, password reset, billing
        receipts). We do not send marketing email unless you have explicitly opted in.
      </P>

      <H3>Cookies</H3>
      <P>
        The site uses a single session cookie set by Clerk for authentication. We do not use
        advertising or tracking cookies. Analytics, if enabled, are collected in aggregate and
        do not identify individual users.
      </P>

      <H2>3. Legal basis for processing (EU/UK users)</H2>
      <Table
        headers={['Purpose', 'Legal basis']}
        rows={[
          ['Providing the service', 'Performance of a contract (Article 6(1)(b) GDPR)'],
          ['Fraud prevention and security', 'Legitimate interest (Article 6(1)(f) GDPR)'],
          ['Billing and tax compliance', 'Legal obligation (Article 6(1)(c) GDPR)'],
          ['Optional marketing emails', 'Consent (Article 6(1)(a) GDPR)'],
        ]}
      />

      <H2>4. Sub-processors</H2>
      <P>
        We share personal data only with the following service providers, each bound by
        data processing agreements:
      </P>
      <Table
        headers={['Provider', 'Purpose', 'Location']}
        rows={[
          ['Clerk', 'Authentication and session management', 'United States'],
          ['Stripe', 'Payment processing', 'United States'],
          ['Fly.io', 'Application hosting and database', 'United States / EU (configurable)'],
          ['Resend', 'Transactional email delivery', 'United States'],
        ]}
      />
      <P>
        Transfers to the United States are covered by standard contractual clauses or the
        provider's participation in the EU–US Data Privacy Framework, as applicable.
      </P>

      <H2>5. Data retention</H2>
      <UL items={[
        'Account data: retained while your account is active, then deleted within 30 days of account closure.',
        'Billing records: retained for seven years to meet Canadian and EU accounting requirements.',
        'Usage logs: deleted on a rolling 90-day basis.',
      ]} />

      <H2>6. Your rights</H2>
      <P>
        Depending on where you live, you may have the right to:
      </P>
      <UL items={[
        'Access a copy of the personal data we hold about you.',
        'Correct inaccurate data.',
        'Request deletion of your data ("right to be forgotten").',
        'Request that we restrict processing while a dispute is resolved.',
        'Receive your data in a portable, machine-readable format.',
        'Object to processing based on legitimate interest.',
        'Withdraw consent at any time (where processing is based on consent).',
      ]} />
      <P>
        To exercise any of these rights, email{' '}
        <A href="mailto:privacy@clusterpilot.sh">privacy@clusterpilot.sh</A>. We will respond
        within 30 days. EU/UK users may also lodge a complaint with their national supervisory
        authority.
      </P>

      <H2>7. Canadian residents (PIPEDA)</H2>
      <P>
        ClusterPilot is operated by a Canadian business and complies with Canada's Personal
        Information Protection and Electronic Documents Act (PIPEDA). The rights in section 6
        apply equally to Canadian residents. To make an access or correction request, or to
        raise a privacy concern, contact{' '}
        <A href="mailto:privacy@clusterpilot.sh">privacy@clusterpilot.sh</A>.
      </P>

      <H2>8. Security</H2>
      <P>
        All data is encrypted in transit using TLS 1.2 or higher. Data at rest on Fly.io is
        encrypted using AES-256. Access to production systems is restricted to named individuals
        and protected by multi-factor authentication.
      </P>

      <H2>9. Children</H2>
      <P>
        ClusterPilot is not directed at children under 16. We do not knowingly collect personal
        data from children. If you believe we have done so in error, contact us and we will
        delete it promptly.
      </P>

      <H2>10. Changes to this policy</H2>
      <P>
        We may update this policy from time to time. Material changes will be communicated by
        email to registered users at least 14 days before they take effect. The "Last updated"
        date at the top of this page will always reflect the most recent revision.
      </P>

      <H2>Contact</H2>
      <P>
        Frankly Labs<br />
        Canada<br />
        <A href="mailto:privacy@clusterpilot.sh">privacy@clusterpilot.sh</A>
      </P>
    </LegalPage>
  )
}
