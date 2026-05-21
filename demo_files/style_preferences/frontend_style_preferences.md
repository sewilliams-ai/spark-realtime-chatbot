Guidelines:
- Generate complete HTML documents including <!DOCTYPE html>, <html>, <head>, and <body>.
- Use modern HTML5, CSS3, and vanilla JavaScript.
- For styling, use inline styles or a <style> block in the <head>.
- For interactivity, use a <script> block at the end of the <body>.
- Ensure the generated HTML is self-contained and runnable in a browser.
- Response Format: Start your response with <!DOCTYPE html> and end with </html>. NEVER include html backticks (```) or any other text before or after the HTML code.

The page should look like a premium Apple/Nike-style hero for an unnamed product.

---

Layout requirements:

Reset the page first: zero out body margin and padding, and apply
border-box sizing to all elements. This is non-negotiable — without it,
centering will be off by a few pixels and look wrong.

Centering rules for every horizontally-centered section (hero, benefits,
bottom teaser):
- Use a flex container with align-items center and justify-content center
as the centering mechanism. Do NOT rely on text-align alone.
- Inside each section, wrap content in an inner container with an
explicit max-width (around 720px for prose, 1100px for grids) and use
margin 0 auto on that wrapper. Centering without a max-width does
nothing — both must be present together.
- For rows of buttons or CTAs, the row itself must be a flex container
with justify-content center and a gap between items.

---

Style:
- Background: #050505 (near-black)
- Primary text: #f0f0f0 (soft white)
- Subdued text: #888 (gray)
- Primary CTA background: #00ff9d (electric green) — ONLY the main CTA button
- Cyan #00f3ff used SPARINGLY — only tiny accents like benefit numbers (01, 02, 03)
- Do NOT use cyan for headlines, body text, or button backgrounds.
- Do NOT use blue, purple, yellow, orange, red, or any other primary color.
- Generous spacing, minimal glow, premium, calm, modern.
