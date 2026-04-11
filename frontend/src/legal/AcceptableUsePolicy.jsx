import LegalPage, { H2, P, UL, A } from './LegalPage'

export default function AcceptableUsePolicy() {
  return (
    <LegalPage title="Acceptable Use Policy" lastUpdated="April 2026">

      <P>
        This Acceptable Use Policy ("<strong>AUP</strong>") applies to all users of
        ClusterPilot, including the self-hosted and hosted tiers. It describes what you
        may and may not do when using the service. Violations may result in suspension or
        termination of your account.
      </P>

      <H2>1. Permitted uses</H2>
      <P>ClusterPilot is designed for:</P>
      <UL items={[
        'Submitting and monitoring legitimate HPC workloads on clusters you are authorised to use.',
        'Academic and scientific research.',
        'Software development and testing of HPC workflows.',
        'Educational purposes, including teaching cluster job submission.',
      ]} />

      <H2>2. Prohibited conduct</H2>

      <H2 style={{}}>2a. Illegal and harmful activity</H2>
      <P>You must not use ClusterPilot to:</P>
      <UL items={[
        'Violate any applicable law or regulation.',
        'Generate, distribute, or facilitate malicious code, malware, or exploits.',
        'Conduct unauthorised access to any computer system, network, or account.',
        'Process data you do not have the legal right to process.',
        'Violate the intellectual property rights of any third party.',
      ]} />

      <H2>2b. Abuse of the service</H2>
      <UL items={[
        'Do not share your account credentials or API access with others. Each user must have their own account.',
        'Do not deliberately submit requests designed to generate an excessive number of API calls or overload the hosted proxy.',
        'Do not attempt to reverse-engineer, decompile, or extract the hosted proxy logic or any Anthropic API keys managed by Frankly Labs.',
        'Do not use automated tooling to hammer the API endpoint beyond what a legitimate single-user workflow would generate.',
      ]} />

      <H2>2c. Cluster policies</H2>
      <P>
        ClusterPilot submits jobs to HPC clusters on your behalf. You remain solely
        responsible for complying with the acceptable use policies of your cluster
        operator (e.g., Compute Canada / DRAC, NSF ACCESS, EuroHPC, your institution).
        Common requirements include:
      </P>
      <UL items={[
        'Using allocations only for the purpose for which they were granted.',
        'Not sharing cluster credentials or allocation accounts.',
        'Respecting storage quotas and scratch space limits.',
        'Not submitting jobs intended to circumvent fair-share scheduling.',
      ]} />
      <P>
        A breach of your cluster operator's AUP is a breach of this AUP. Frankly Labs
        is not liable for sanctions imposed by your cluster operator.
      </P>

      <H2>2d. AI misuse</H2>
      <P>
        The AI script generation feature exists to help you produce correct, cluster-aware
        SLURM scripts. You must not attempt to:
      </P>
      <UL items={[
        'Prompt-inject instructions designed to override safety guidelines.',
        'Generate scripts whose primary purpose is to disrupt cluster infrastructure.',
        'Extract or infer the contents of the system prompt or any Anthropic configuration.',
      ]} />

      <H2>3. Reporting abuse</H2>
      <P>
        If you observe activity that violates this AUP, please report it to{' '}
        <A href="mailto:hello@clusterpilot.sh">hello@clusterpilot.sh</A>. Include as much
        detail as possible. We treat all reports confidentially.
      </P>

      <H2>4. Enforcement</H2>
      <P>
        Frankly Labs reserves the right to investigate suspected violations and to take any
        action we deem appropriate, including:
      </P>
      <UL items={[
        'Issuing a warning.',
        'Temporarily suspending access to the hosted tier.',
        'Permanently terminating your account.',
        'Reporting illegal activity to law enforcement.',
      ]} />
      <P>
        We will endeavour to give prior notice where practicable, but reserve the right to
        act immediately where the breach is serious or ongoing.
      </P>

      <H2>5. Changes to this policy</H2>
      <P>
        We may update this AUP from time to time. Material changes will be communicated
        by email at least 14 days in advance. Continued use of the service constitutes
        acceptance of the updated policy.
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
