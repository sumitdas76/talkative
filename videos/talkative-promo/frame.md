---
version: alpha
name: Talkative Nebula — Frame (video / frame layer)
description: >
  Bespoke, dramatic dark-gradient system for the Talkative promo — replaces the earlier flat
  "blue-professional" pass, which read as bland/corporate on review. Deep near-black navy canvas,
  a swirling three-color glow system (cobalt blue / violet / magenta) driving animated ambient
  light behind every frame, glassmorphic cards, high-contrast white display type with a soft
  colored glow, and motion that leans hard into spring pops, glow blooms, and camera pushes
  rather than restrained holds. The frame is the unit (1920×1080). Composition + motion direction
  both in scope this pass — this system is meant to be felt, not just read.
unit: the frame — 1920×1080 primary
principle: dark canvas · swirling glow does the atmosphere · white type carries the read · every
  frame has at least one moment of real motion drama, not just a reveal-and-hold

colors:
  bg: "#0A0E27"
  bg-deep: "#050714"
  primary: "#2563EB"
  secondary: "#7C3AED"
  tertiary: "#EC4899"
  text: "#FFFFFF"
  text-muted: "#A5B4CB"
  text-light: "#6B7A99"
  accent-light: "rgba(59, 130, 246, 0.16)"
  accent-medium: "rgba(139, 92, 246, 0.28)"
  border: "rgba(255, 255, 255, 0.14)"
  border-glow: "rgba(96, 165, 250, 0.45)"
  card-bg: "rgba(255, 255, 255, 0.05)"
  glow-blue: "#3B82F6"
  glow-violet: "#8B5CF6"
  glow-pink: "#F472B6"
  positive: "#34D399"
  negative: "#F87171"

radii:
  pill: "100px"
  card-lg: "24px"
  card-md: "18px"
  card-sm: "14px"
  bar: "8px"
  circle: "50%"

typography:
  body:    { fontFamily: "Inter", cqw: 0.95, weight: 400, lineHeight: 1.55, color: "text-muted" }
  eyebrow: { fontFamily: "Inter", cqw: 0.85, weight: 700, tracking: "0.1em", upper: true, color: "glow-blue" }
  tag:     { fontFamily: "Inter", px: 13, weight: 700, color: "text" }
  h3:      { fontFamily: "Inter", cqw: 1.6, weight: 700, lineHeight: 1.25, tracking: "-0.01em", color: "text" }
  stat-num:{ fontFamily: "Inter", cqw: 2.2, weight: 900, lineHeight: 1.0, color: "glow-blue" }
  h2:      { fontFamily: "Inter", cqw: 3.0, weight: 900, lineHeight: 1.08, tracking: "-0.02em", color: "text" }
  h1:      { fontFamily: "Inter", cqw: 4.4, weight: 900, lineHeight: 1.05, tracking: "-0.02em", color: "text" }
  wordmark:{ fontFamily: "Inter", cqw: 4.6, weight: 900, lineHeight: 1.0, tracking: "-0.02em", color: "text" }

spacing:
  pad-x: "5cqw"
  pad-y-top: "5cqw"
  gap-cards: "1.6cqw"
  accent-line: "72px × 5px"

components:
  glass-card:
    backgroundColor: "{colors.card-bg}"
    border: "1.5px solid {colors.border}"
    rounded: "{radii.card-lg}"
    shadow: "soft outer glow in the nearest swirl color (blue/violet/pink), 24-40px blur, 15-25% opacity — this IS the shadow system, not a neutral drop-shadow"
    description: "Universal content card — glassmorphic, never flat-opaque. A thin glowing border reads as the premium signal instead of restraint."
  glow-badge:
    backgroundColor: "radial-gradient center-out, swirl color at 20% opacity fading to transparent"
    rounded: "50%"
    description: "Icon badges sit inside a soft glow halo, not a flat tinted circle — the glow should visibly bloom on entrance."
  cta-wordmark:
    textColor: "{colors.text}"
    glow: "layered text-shadow / blurred duplicate in glow-blue and glow-violet, offset ~0, blur 20-40px"
    description: "The brand wordmark always carries a soft dual-color glow — this is the one place both accent hues appear together, deliberately."
  swirl-field:
    elements: "2-4 large soft-blurred radial gradient blobs (blue / violet / pink) at low opacity (12-22%), positioned off-grid, in slow continuous drift + gentle scale pulse (sine loop) — never a static gradient PNG, always alive"
    description: "The atmosphere layer behind every single frame, not just cover/closing. This is what makes the video feel 'swirling' rather than flat — no frame should read as pure flat color."
  accent-line:
    backgroundColor: "linear-gradient(90deg, {colors.glow-blue}, {colors.glow-violet})"
    size: "72×5, 2.5px radius"
    description: "Gradient rule, not a flat cobalt bar — used as an underline/divider accent."
  progress-rings:
    elements: "concentric thin rings, gradient-stroked (blue→violet→pink sweep), used on the closing frame at minimum"
    description: "Replaces flat closing-rings with a gradient stroke for extra drama on the terminal frame."

---

# Talkative Nebula — Frame (video / frame layer)

## Why this exists (read first)

The first pass used a restrained, flat, light "consulting" system (cream canvas, one flat cobalt
accent, no shadows, no motion drama). Reviewed against the real cut, it read as **bland — no
animation energy, no aesthetic pop, no color, no music**. This spec throws that restraint out
deliberately. The brief now is: **dramatic, colorful, alive.** Every frame must have a genuine
"wow" motion beat, not just a calm reveal-and-hold. Stillness is no longer the premium signal —
motion and glow are.

## Overview

A **dark-canvas, glow-driven system**: near-black deep-navy ground (`#0A0E27`), with a living
"swirl field" of soft blurred color blobs (blue → violet → pink) drifting slowly behind every
frame — this is the frame's atmosphere and its "swirling colors," always present, always moving,
never a static flat background. White, heavy-weight Inter type (`700–900`) carries the read at
high contrast against the dark ground. Cards are **glassmorphic**: translucent white fill, a thin
glowing border, and a soft colored outer glow standing in for the shadow system entirely.

**Key characteristics at frame scale:**

- **Deep navy/near-black ground** (`#0A0E27`, deeper `#050714` in vignette corners) on every
  frame — never white, never flat cream.
- **Swirl field always live** — 2–4 soft blurred gradient blobs in blue/violet/pink, slowly
  drifting + pulsing behind the content on every single frame, not just cover/closing.
- **White heavy type** (Inter 700–900) for all display copy; a soft colored glow (not a flat
  color swap) is the accent move on hero words.
- **Glassmorphic cards** — translucent fill, glowing border, soft colored outer glow (the shadow
  IS the glow, never neutral gray).
- **Real motion drama every frame** — a spring-pop with visible overshoot, a glow bloom, a
  camera push, or a chromatic/glitch accent — at least one per frame, timed to a beat the VO
  actually lands on.

## The Frame

### Frame Craft Bar

- **Pop** — something in every frame visibly springs, blooms, or pushes — never just fades in flat.
- **Glow** — the swirl field is visibly alive (drifting/pulsing) in the background of every frame; no frame is a flat solid color.
- **Contrast** — white type against the deep navy ground at full weight (700+) reads instantly at a glance.
- **Reference** — aim at a modern AI/SaaS launch trailer (think: product keynote sizzle reel) — failure looks like the old cream-and-cobalt deck.

- **Primary:** 1920×1080 (16:9). Display authored in **`cqw`** (`px ÷ 1920 × 100 = cqw`).
- **Safe area:** `pad-x` 5cqw; keep the bottom ~17% clear for captions even when disabled.

**The container law (load-bearing).** Every frame ground sets `container-type: size`; ALL
frame-relative units are `cqw`/`cqh` against it — never `vw`.

## Colors

`{colors.bg}` deep navy is the universal ground, always with the swirl-field atmosphere layer on
top of it (never a bare flat fill). `{colors.primary}` (blue), `{colors.secondary}` (violet), and
`{colors.tertiary}` (pink) are ALL live accents this pass — unlike the old single-accent rule,
this system deliberately uses the three-color swirl together in glows, gradients, and blob fields.
Headlines are `{colors.text}` white; body/secondary copy is `{colors.text-muted}`. Cards fill
`{colors.card-bg}` translucent with a `{colors.border-glow}` glowing edge.

## Typography

Single weight-driven ramp, all Inter (bundled, renders deterministically with zero setup): `h1`
4.4cqw / 900 for hero lines, `h2` 3.0cqw / 800 for secondary headlines, `wordmark` 4.6cqw / 900 for
the brand mark, `stat-num` 2.2cqw / 900 in glow-blue for callout numbers, `body` 0.95cqw / 500
muted for supporting copy. No italics. Headlines are always white — color/drama comes from glow
effects and the swirl field behind the type, not from tinting the type itself (keeps every line
readable at a glance against the dark ground).

## Depth & Motion Register

Depth now comes from **glow and blur**, not flat tint-and-border:

- **Glass cards** — translucent fill + glowing border + soft colored outer glow.
- **Swirl field** — the atmosphere layer's blur and drift creates real spatial depth behind flat content.
- **Motion drama** — spring-pop entrances with visible overshoot (`back.out`), glow blooms timed
  to VO beats, camera pushes/zooms on section boundaries, a chromatic-glitch or particle accent on
  at least one hero moment in the video (the "Talkative" reveal is the natural home for this).

**Ceiling:** keep white type legible — glow/blur effects live in the background and on accents,
never smeared across body-weight text itself.

## Frame Treatments (mapped to this project's actual 6 frames)

### 1 · Cloud hook (tension · move: swirl field pulses on the beat)

Deep navy ground, swirl field already drifting at t=0 (not a cold static open). White `h1`-weight
type builds per phrase on the VO cue, each phrase-arrival triggering a visible glow-pulse in the
swirl field behind it (the background reacts to the words landing — this is the "wow" moment for
this frame, replacing the old flat accent-line).

### 2 · The turn (relief · move: spring-pop + glow bloom)

Hard cut. The app icon spring-pops in with real overshoot inside a glowing halo (glow-badge), a
blue→violet gradient light bloom sweeps once behind the wordline as it lands. This is the
video's first real "pop" moment — it should feel like a release of energy after Frame 1's tension.

### 3 · Security stack (trust · move: shield glow-pulse, staccato pops)

A glowing shield badge (blue glow halo, pulsing gently) anchors the top. Each of the four phrases
spring-pops into a glass-card-style pill (not bare text on flat ground) with a quick glow flash on
arrival — staccato energy, matching the quick cadence of the VO.

### 4 · Feature grid (evidence · move: glass cards + traveling gradient sweep + camera push)

Four glassmorphic cards (translucent, glowing border) assemble on their VO cues. The traveling
glow sweep (already planned) now sweeps the full blue→violet→pink gradient, not a flat cobalt
tint. Camera push-in intensifies toward the end as the grid completes — visible, not subtle.

### 5 · Same app, new name (breather · move: still allowed, but glowing)

This frame is still the video's deliberate calm beat (per the story's own pacing) — but "calm"
now means the swirl field keeps drifting softly behind the type and "Talkative" carries its glow
treatment, not that the frame goes flat and static. The one restrained beat in an otherwise
dramatic video, not a return to the old system.

### 6 · Close (climax · move: spring bloom + dual-glow wordmark + gradient rings)

The icon spring-blooms from zero with real overshoot and a glow flash; the "Talkative" wordmark
carries its signature dual-color glow (blue+violet); the closing rings sweep a gradient stroke
(blue→violet→pink) instead of flat thin lines. This is the video's climax frame — it should be
the most visually alive frame in the piece, not another calm hold.

## Composition Rules

### Do

- Keep the swirl field alive and drifting behind **every** frame — this is non-negotiable, it's
  the thing that was missing.
- Give every frame at least one real spring-pop, glow-bloom, or camera-push moment timed to a VO beat.
- Use all three accent hues (blue/violet/pink) across the video's glows and gradients — don't
  collapse back to a single flat accent.
- Keep white type at 700+ weight for instant legibility against the dark ground.

### Don't

- No flat, static, single-color backgrounds — ever. The swirl field must always be present and moving.
- No restrained/calm treatment outside Frame 5's deliberate breather.
- No neutral gray shadows — glow (colored, soft) is the only depth cue.
- Don't let glow/blur effects reduce text legibility — glow lives behind and around type, not on top of it.

## Numerals & Claims (hard rule, unchanged)

Every on-screen claim traces to the real product facts already established in `BRIEF.md` / the
storyboard — nothing new invented for this visual pass. Only the LOOK and MOTION changed, not the
content or claims.

## Known Gaps

- Motion techniques (spring-pop overshoot, glow-bloom, chromatic-glitch, camera-push) resolve via
  the standard rule mapping in `hyperframes-animation/blueprints-index.md` — this file specifies
  the look + the motion REGISTER (dramatic, glow-driven), not literal GSAP code.
- Font: Inter only, weights strictly limited to 400/700/900 — the renderer's actual bundled cuts
  for this family (asking for anything else gives a synthetic weight, not a real cut).
