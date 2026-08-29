from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str  # postgresql+asyncpg://...

    # Clerk
    clerk_secret_key: str          # sk_...
    clerk_webhook_secret: str      # whsec_... (Svix)

    # Stripe
    stripe_secret_key: str         # sk_...
    stripe_webhook_secret: str     # whsec_...
    stripe_price_id_monthly: str   # price_...
    stripe_price_id_annual: str    # price_...
    stripe_coupon_pi_group: str = "pi_group_15"

    # Resend
    resend_api_key: str            # re_...
    resend_from_address: str = "ClusterPilot <hello@clusterpilot.sh>"
    resend_forward_to: str = "clusterpilot@juliafrank.net"
    resend_webhook_secret: str = ""  # whsec_... from Resend inbound webhook settings

    # Anthropic master key (used by the proxy endpoint)
    anthropic_api_key: str  # ANTHROPIC_API_KEY env var

    # Hosted generation allowance, counted per user per calendar month (UTC).
    # Opus is chosen per job on F2; once the Opus allowance is spent the proxy
    # substitutes fallback_model and says so, and once the total cap is reached
    # it refuses with 429. Nothing fails silently.
    opus_monthly_allowance: int = 15    # OPUS_MONTHLY_ALLOWANCE
    total_monthly_cap: int = 150        # TOTAL_MONTHLY_CAP
    fallback_model: str = "claude-sonnet-5"  # FALLBACK_MODEL

    # App
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:5173", "https://clusterpilot.sh", "https://app.clusterpilot.sh"]


settings = Settings()  # type: ignore[call-arg]
