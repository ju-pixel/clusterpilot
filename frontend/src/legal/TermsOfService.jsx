import LegalPage, { H2, H3, P, UL, A } from './LegalPage'

export default function TermsOfService() {
  return (
    <LegalPage title="Terms of Service" lastUpdated="April 2026">

      <P>
        These Terms of Service ("<strong>Terms</strong>") govern your access to and use of
        ClusterPilot, operated by Frankly Labs ("<strong>we</strong>", "<strong>us</strong>",
        "<strong>our</strong>"). By creating an account or using the hosted tier, you agree to
        these Terms.
      </P>
      <P>
        If you are using the self-hosted, open-source version of ClusterPilot under the MIT
        Licence, these Terms do not apply. The MIT Licence governs that use instead.
      </P>

      <H2>1. The service</H2>
      <P>
        ClusterPilot provides an AI-assisted SLURM job submission interface accessible via
        the command-line tool and, for paid users, a hosted proxy that manages an Anthropic
        API key on your behalf. The service is provided "as is" — see section 9.
      </P>

      <H2>2. Accounts</H2>
      <P>
        You must be at least 18 years old (or the age of majority in your jurisdiction,
        whichever is greater) to create an account. You are responsible for maintaining
        the security of your account credentials. You must notify us immediately at{' '}
        <A href="mailto:hello@clusterpilot.sh">hello@clusterpilot.sh</A> if you suspect
        unauthorised access.
      </P>
      <P>
        One account per person. Organisation-level accounts are not currently offered;
        each individual on a research team should create their own account.
      </P>

      <H2>3. Paid tier</H2>

      <H3>What you get</H3>
      <UL items={[
        'A managed Anthropic API key — no need to supply your own.',
        'Email and ntfy.sh push notifications for job events.',
        'Access to the hosted proxy endpoint at api.clusterpilot.sh.',
      ]} />

      <H3>Pricing</H3>
      <P>
        The paid tier is billed at $4 USD per month (or as displayed at checkout). Founding
        Member pricing, where offered, is locked to the rate at time of subscription for
        as long as the subscription remains active without interruption.
      </P>

      <H3>Payment</H3>
      <P>
        Payments are processed by Stripe. Your card is charged at the start of each billing
        period. By providing a payment method, you authorise us to charge it for recurring
        monthly fees.
      </P>

      <H3>Cancellation</H3>
      <P>
        You may cancel your subscription at any time from your account settings. Cancellation
        takes effect at the end of the current billing period. We do not issue refunds for the
        remaining days in a billing period, except where required by law.
      </P>

      <H3>Free tier on cancellation</H3>
      <P>
        On cancellation, your account reverts to the free, self-hosted tier. You can continue
        using ClusterPilot indefinitely with your own Anthropic API key.
      </P>

      <H2>4. Acceptable use</H2>
      <P>
        Your use of ClusterPilot must comply with our{' '}
        <a href="/acceptable-use" style={{ color: '#FFB866' }}>Acceptable Use Policy</a>.
        Key restrictions: no illegal activity, no credential sharing, no deliberate overloading
        of the API, and no use that violates the policies of your HPC cluster operator.
      </P>

      <H2>5. Intellectual property</H2>
      <P>
        The ClusterPilot source code is released under the MIT Licence. SLURM scripts generated
        by the AI are not subject to copyright — they are produced from your input and belong
        to you. We claim no ownership over generated scripts or your job data.
      </P>
      <P>
        The ClusterPilot name, logo, and site design are trademarks of Frankly Labs. You may
        not use them without written permission.
      </P>

      <H2>6. Privacy</H2>
      <P>
        Your use of ClusterPilot is also governed by our{' '}
        <a href="/privacy" style={{ color: '#FFB866' }}>Privacy Policy</a>, which is
        incorporated into these Terms by reference.
      </P>

      <H2>7. Third-party services</H2>
      <P>
        The service relies on Anthropic's API for AI generation, Clerk for authentication,
        Stripe for billing, and Fly.io for hosting. These providers have their own terms and
        policies. Disruption of a third-party service may affect ClusterPilot availability;
        we are not liable for such disruptions.
      </P>

      <H2>8. Suspension and termination</H2>
      <P>
        We may suspend or terminate your account without notice if you breach these Terms or
        our Acceptable Use Policy, or if we are required to do so by law. We will endeavour
        to notify you by email where practicable. On termination, your data will be deleted
        in accordance with the Privacy Policy.
      </P>
      <P>
        You may terminate your account at any time by contacting{' '}
        <A href="mailto:hello@clusterpilot.sh">hello@clusterpilot.sh</A>.
      </P>

      <H2>9. Disclaimer of warranties</H2>
      <P>
        ClusterPilot is provided "as is" and "as available" without warranties of any kind,
        express or implied. We do not warrant that the service will be uninterrupted, error-free,
        or that AI-generated SLURM scripts will be correct or suitable for your use case.
        You are responsible for reviewing generated scripts before submitting them to a cluster.
      </P>

      <H2>10. Limitation of liability</H2>
      <P>
        To the maximum extent permitted by applicable law, Frankly Labs' total liability to
        you for any claim arising from these Terms or the service is limited to the total
        fees you paid us in the twelve months preceding the claim. We are not liable for
        indirect, incidental, consequential, or punitive damages, including loss of data,
        lost HPC allocations, or failed experiments.
      </P>

      <H2>11. Governing law and disputes</H2>
      <P>
        These Terms are governed by the laws of Canada and the province of Manitoba, without
        regard to conflict-of-law principles. Disputes shall be resolved by binding
        arbitration under the Arbitration Act (Manitoba), except that either party may seek
        injunctive relief in a court of competent jurisdiction.
      </P>

      <H2>12. Changes to these Terms</H2>
      <P>
        We may update these Terms from time to time. Material changes will be communicated
        by email at least 14 days before they take effect. Continued use of the service after
        the effective date constitutes acceptance of the updated Terms.
      </P>

      <H2>Contact</H2>
      <P>
        Frankly Labs<br />
        Canada<br />
        <A href="mailto:hello@clusterpilot.sh">hello@clusterpilot.sh</A>
      </P>
    </LegalPage>
  )
}
