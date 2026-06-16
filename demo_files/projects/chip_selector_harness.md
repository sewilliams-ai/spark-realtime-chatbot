## 

Build a static marketing landing page, not an app. 
Create a compact single-file HTML/CSS hero section under 6,000 tokens. No JS, no external assets, no comments.

DO NOT build the chip selection product.
DO NOT build a dashboard.
DO NOT build a form, table, selector, chat, workflow builder, or interactive interface.
This is only a product launch hero page that advertises the product.

---

## Layout

Hero copy:
The copmonent selection agent for
rapid prototyping

Turn product ideas into chip recommendations before you build.

Compare options. Understand tradeoffs. Move faster.

Buttons:
Get Early Access →
Watch the Demo

For the benefit row specifically: it must be a CSS grid with three equal
columns and a shared max-width wrapper. Do not use floats, inline-block,
or a flex row for the three columns — only grid.

For the top nav: flex with space-between, wrapped in a max-width
container that is itself margin 0 auto.

---
## Allowed Sections

ALLOWED SECTIONS — Generate EXACTLY these four, in this order, and NOTHING ELSE:

1. Top nav:
   - text logo on the left (use the invented name "Harness")
   - 3-4 nav links on the right: How it works, Book Demo, Get Early Access

2. Main hero:
   - centered headline (use exact copy from above)
   - centered subheadline (use exact copy from above)
   - centered button row with two buttons
   - Hero ends at the button row. No decorative graphic, chip module, or visual element below the buttons.

3. Benefit row — exactly 3 columns in a CSS grid:
   01 Choose faster — Cut through thousands of chip options.
   02 Avoid redesigns — Pick the right part before mistakes get expensive.
   03 Understand tradeoffs — See the reasons, risks, and alternatives.

   Each benefit must be a rectangular bordered card, not bare text:
   - 1px solid border in dark gray (#222 or similar, blending with the
     near-black background)
   - 12px border-radius
   - ~32px internal padding
   - Card background slightly lighter than the page (e.g. #0a0a0a)
   The number (01, 02, 03) sits at the top in cyan accent. The title and
   description go below, in white and gray respectively.

4. Bottom teaser:
   Headline: "From product idea to chip recommendation"
   A 3-card row showing the flow: Product idea → Chip fit analysis → Recommendation
   Each card contains ONLY its name (e.g., "Product idea") with arrows between cards.
   No descriptions, labels, sub-text, or per-card explanations.

The page consists of exactly the four sections above and no others.
After writing the bottom teaser, immediately close </body></html> and stop.