# Security Policy

  ## Reporting a Vulnerability

  If you discover a security vulnerability in Comic Chaos, please report it **privately** — do not open a public GitHub
  issue.

  **Email:** sbfroyland@gmail.com

  Include:
  - A description of the vulnerability
  - Steps to reproduce
  - Potential impact

  You can expect an initial response within **48 hours**. We will work with you to understand the issue and coordinate a
   fix before any public disclosure.

  ## Supported Versions

  | Version | Supported |
  |---------|-----------|
  | 0.1.x   | Yes       |

  ## Security Considerations

  ### API Keys

  This project requires an OpenAI API key to function. To protect your key:

  - **Never commit `.env` files.** The `.gitignore` already excludes `.env`, but always verify before pushing.
  - Use `.env.example` as a reference — it contains placeholder values only.
  - If you suspect your key has been exposed, rotate it immediately at
  [platform.openai.com/api-keys](https://platform.openai.com/api-keys).

  ### Session Storage

  Comic sessions are stored in-memory on the server. This means:
  - Sessions are lost on server restart.
  - There is no authentication or session isolation — this is intended for single-user or trusted-network use.
  - Do not expose the app to the public internet without adding authentication and rate limiting.

  ### Content Moderation

  The Narratron system prompt includes content policy rules enforced at the LLM level. The OpenAI image generation API
  also applies its own moderation. However, neither layer is a guarantee — do not rely on them as your sole safety
  mechanism in a public deployment.
