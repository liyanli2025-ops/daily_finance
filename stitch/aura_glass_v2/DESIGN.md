```markdown
# Design System Specification: The Luminous Lens

## 1. Overview & Creative North Star
The Creative North Star for this design system is **"The Luminous Lens."** 

We are moving away from the "flat web" era into an editorial space defined by depth, refraction, and atmospheric lighting. This system treats the interface as a high-end physical object—specifically, layers of frosted glass suspended in a pressurized, light-filled environment. 

Inspired by the provided logo's "tech-bear" aesthetic, we utilize glowing edges, internal binary-like patterns, and a sophisticated interplay between deep violets and golden highlights. By embracing intentional asymmetry and overlapping "glass" containers, we break the rigid grid, creating a layout that feels curated and premium rather than generated.

---

## 2. Colors
Our palette is rooted in a deep, atmospheric violet core, balanced by the "high-transparency" requirements of light mode.

### The "No-Line" Rule
**Explicit Instruction:** Designers are prohibited from using 1px solid borders for sectioning or containment. Structural boundaries must be defined solely through background shifts or tonal transitions.
*   **Example:** A `surface-container-low` card sitting on a `surface` background creates a natural, soft edge.
*   **The Exception:** If a boundary is strictly required for accessibility, use a "Ghost Border" (the `outline-variant` token at 10-20% opacity).

### Surface Hierarchy & Nesting
Instead of a flat grid, treat the UI as a series of physical layers. Use the `surface-container` tiers (Lowest to Highest) to create "nested" depth.
*   **Background (#0c0e12):** The infinite void.
*   **Surface-Container-Low:** The first layer of glass.
*   **Surface-Container-Highest:** Active or "closest" elements that demand immediate attention.

### The "Glass & Gradient" Rule
To move beyond a standard UI feel, use **Glassmorphism** for floating elements. 
*   **Technique:** Apply a semi-transparent `surface` color with a `backdrop-blur` (16px to 32px).
*   **Signature Textures:** Use subtle linear gradients for CTAs, transitioning from `primary` (#b6a0ff) to `primary-dim` (#7e51ff) at a 135-degree angle. This mimics the "glowing edge" seen in the tech-bear logo.

---

## 3. Typography
We use **Manrope** for its technical precision and modern geometric forms. The hierarchy is designed for editorial impact, using extreme scale shifts to guide the eye.

*   **Display (lg/md):** Reserved for hero moments. Use `display-lg` (3.5rem) to establish a bold, authoritative presence. Letter spacing should be slightly tight (-0.02em) to maintain a "lockup" feel.
*   **Headlines:** Used for section titles. Ensure generous vertical spacing (using the `12` or `16` spacing tokens) to allow the typography to "breathe" against the glassy backgrounds.
*   **Body (lg/md):** Our primary communication tool. Use `body-lg` (1rem) for high readability. In dark mode, ensure `on-surface-variant` is used for secondary text to maintain atmospheric depth.
*   **Labels:** Specifically for technical metadata. These should be uppercase with a slight letter spacing (+0.05em) to mimic the "code" aesthetic of the tech-bear's internal data.

---

## 4. Elevation & Depth
Elevation is not achieved through shadows alone, but through **Tonal Layering**.

### The Layering Principle
Depth is "stacked." Place a `surface-container-lowest` card on a `surface-container-low` section to create a soft, natural "recessed" lift. This mimics the way the tech-bear logo's internal elements appear to sit *inside* the glass.

### Ambient Shadows
When an element must "float" (e.g., a Modal or Popover):
*   **Blur:** 40px - 80px.
*   **Opacity:** 4% - 8%.
*   **Color:** Tint the shadow with `primary` (#7C4DFF) rather than using pure black. This creates a "glow" effect that feels integrated into the atmosphere.

### Glassmorphism & Refraction
In Light Mode, use high-transparency `surface` colors with `backdrop-filter: blur(20px)`. This allows the "colorful background blobs" (using `secondary` and `tertiary` tokens) to bleed through, softening the edges and making the layout feel organic.

---

## 5. Components

### Buttons
*   **Primary:** A gradient fill from `primary` to `primary-container`. Use `xl` roundedness (1.5rem). Add a subtle 1px "inner glow" using `primary-fixed` at 30% opacity on the top edge.
*   **Secondary:** Glass-filled. Use a semi-transparent `surface-variant` with a backdrop blur. No border.

### Input Fields
*   **Style:** Recessed glass. Use `surface-container-lowest` with a subtle inner shadow. 
*   **Active State:** The bottom edge should "glow" with a `primary` (#7C4DFF) line, mimicking the glowing edges of the logo.

### Cards & Lists
*   **No Dividers:** Forbid the use of 1px divider lines. 
*   **Spacing:** Use the `spacing-6` (2rem) or `spacing-8` (2.75rem) tokens to create separation between list items.
*   **Visual Shift:** Use a subtle background hover state change from `surface-container-low` to `surface-container-high`.

### Floating Action Tabs
*   A custom component inspired by the logo's silhouette. A pill-shaped container using `surface-bright` at 60% opacity, featuring a high-intensity backdrop blur.

---

## 6. Do's and Don'ts

### Do
*   **DO** use the `tertiary` (#ffe792) color for small, high-impact "data" points or accents (inspired by the bear's internal candle-stick charts).
*   **DO** use intentional asymmetry. Overlap a glass card across two background sections to create a sense of three-dimensional space.
*   **DO** lean into the "atmospheric" nature of dark mode by using `surface-dim` for large background areas.

### Don't
*   **DON'T** use pure black (#000000) for containers unless it is the `surface-container-lowest` used for deep recessed areas.
*   **DON'T** use standard 4px border radii. Always use the `md` (0.75rem) to `xl` (1.5rem) scale to maintain the "smooth-molded glass" aesthetic.
*   **DON'T** clutter the UI. If a section feels heavy, increase the spacing token and reduce the opacity of the glass container.

---

*Director's Final Note: Remember, every element should feel like it was carved from light and glass. If it looks like a standard "box," it isn't finished.*```