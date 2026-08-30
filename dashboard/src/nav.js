// Left-hand navigation. Its own module so the shell can import it without
// dragging a component in, which is what breaks fast refresh.
export const NAV = [
  { id: "jobs",          icon: "▤", label: "Jobs"          },
  { id: "notifications", icon: "◎", label: "Notifications" },
  { id: "account",       icon: "◈", label: "Account"       },
];

// Founding prices. Keep in step with the Stripe prices on clusterpilot-api,
// the landing page card and README; the yearly one is two months free. A
// group seat is the same price less the permanent 15% group discount.
