---
format: 1920x1080
duration: 21s
message: "Talkative is the only fully offline, free dictation app for Windows — hold a key, speak, and it just works."
arc: PAS with feature-benefit progression
audience: Windows users evaluating voice-dictation tools, privacy-conscious
mode: collaborative
music: energetic modern electronic tech promo underscore, driving synth pulse, confident and upbeat (generated locally via MusicGen, assets/bgm/track.wav)
---

## Video direction

**Revised after review** — the first pass (flat white/cobalt "consulting" system, no motion drama, no music) read as bland. This version leans hard into `frame.md`'s new dramatic dark-glow system.

- **Palette system** (from `frame.md`, by role): canvas = deep navy/near-black (`bg`, #0A0E27), never flat/static — every frame carries a live "swirl field" of 2-4 soft blurred gradient blobs (blue `glow-blue` #3B82F6 / violet `glow-violet` #8B5CF6 / pink `glow-pink` #F472B6) slowly drifting + pulsing behind the content. Display type is white (`text`) at heavy weight (700/900) for contrast. Cards are glassmorphic (`card-bg` translucent fill + `border-glow` glowing edge), never flat-tinted.
- **Motion grammar + reveal model**: spring-pop entrances with real overshoot (`back.out`) are now the default arrival, not a plain fade — paired with a glow-bloom flash on the swirl field timed to the same beat. Reveals still pace to the voiceover cue-by-cue (never front-loaded), but each cue now lands with visible energy, not a calm settle. `power3` eases stay for exits/holds; entrances lean into spring/back eases.
- **Rhythm / held-frame allocation**: Frame 5 remains the one deliberate breather (per the story's own pacing), but even there the swirl field keeps drifting — "calm" no longer means "flat." Every other frame gets at least one real drama beat: a glow-pulse reacting to the VO (F1), a spring-pop + light bloom (F2), staccato glow-flash pops (F3), a full-gradient traveling sweep + camera push (F4), a spring-bloom + dual-glow wordmark + gradient rings (F6, the climax).
- **Negative list**: no flat/static single-color backgrounds anywhere (the swirl field must always be visibly alive), no neutral gray shadows (glow is the only depth cue), no restrained/calm treatment outside Frame 5, no real cursor/browser chrome. Avoid both failure modes: slideshow (front-load-then-freeze) and screensaver (elements drifting with no anchor to the VO) — motion here is deliberate and beat-timed, not decorative wallpaper.

## Frame 1 — Cloud hook

- scene: Bold centered type states the industry default, cold.
- voiceover: "Every other dictation app / sends your voice / to the cloud."
- duration: 3.499s
- transition_in: cut
- status: animated
- src: compositions/frames/01-cloud-hook.html
- type: hook
- persuasion: Pain validation
- beat: skepticism
- blueprint: kinetic-type-beats
- asset_candidates:

narrativeRole: Opens on the shared, unexamined default (cloud dictation) so the turn in Frame 2 lands as relief, not a sales pitch.
keyMessage: Every dictation app you already know sends your voice somewhere else.

blueprint: kinetic-type-beats (Adapt — Hook/flash variant, dramatized)
focal: (typography + the live swirl field)
roles: (none — typography + inline-drawn swirl blobs, not file assets)
sfx: none

Adapt: keep the flash-word-swap signature move, but replace the calm per-word fade with a swirl-field that visibly PULSES (glow-bloom flash) each time a phrase lands, and drop the flat accent-line for a gradient one.
Scene 1 (0.0–1.3s): deep navy canvas, swirl field ALREADY drifting (2-3 soft blue/violet blobs, slow continuous motion — never a cold static open). A blue→violet gradient accent-line draws in dead-center, ~38% down, with a brief glow-flash on arrival.
Scene 2 (1.3–2.3s): as the VO says "Every other dictation app," the phrase springs in (per-word, `back.out` overshoot, not a plain fade) below the accent line, white, ~4.2cqw/900, centered — the swirl field pulses a soft glow-bloom exactly on this arrival.
Scene 3 (2.3–3.0s): as the VO says "sends your voice," the phrase continues on the next line beneath with the same spring-in + glow-pulse; the swirl blobs drift further, sentence now half-built.
Scene 4 (3.0–3.5s): as the VO lands "to the cloud," the final words spring in with one more glow-pulse and the whole line settles — held to the frame's end, swirl field still visibly alive (this is the harness cut into Frame 2, not an authored exit).

## Frame 2 — The turn

- scene: Hard cut to "Talkative doesn't." — the app icon settles in beside the line.
- voiceover: "Talkative doesn't."
- duration: 1.28s
- transition_in: crossfade
- status: animated
- src: compositions/frames/02-the-turn.html
- type: product_intro
- persuasion: Negative contrast
- beat: relief
- blueprint: kinetic-type-beats
- asset_candidates: assets/app-icon.png — Talkative's mic-on-squircle app icon, transparent PNG

narrativeRole: Lands the value claim by beat 2, per the reverse-iceberg rule — resolves the hook's tension in three words.
keyMessage: Talkative is the exception to the cloud-dictation default.

blueprint: kinetic-type-beats (Adapt — Product_Intro/namedrop variant, dramatized)
focal: assets/app-icon.png
roles: assets/app-icon.png = cutout (small, beside the wordline, not full-bleed) — sits inside a glowing halo (glow-badge)
sfx: soft-impact (on the spring-pop landing)

Adapt: keep the namedrop's hard-cut-to-resolve signature move, but the icon now SPRING-POPS with real overshoot inside a glow halo instead of a flat flash-pop, and a blue→violet light bloom sweeps once behind the wordline as it lands — this is the video's first big release-of-energy moment after Frame 1's tension.
Scene 1 (0.0–0.20s): hard cut from Frame 1's swirling navy canvas. The app icon spring-pops in at left-of-center with visible `back.out` overshoot inside a soft glowing halo (blue glow, brief bloom-flash on arrival) — no flat fade, a real pop.
Scene 2 (0.20–1.02s): as the VO says "Talkative doesn't," white bold wordline flash-swaps in beside the icon while a blue→violet light bloom sweeps once behind the pair — the icon and the line read as one glowing lockup, ~35% of frame width, centered.
Scene 3 (1.02–1.28s): settle-and-hold — swirl field keeps drifting softly behind the lockup; the pair sits centered until the harness cut into Frame 3.

## Frame 3 — Security stack

- scene: Four short security/privacy claims land one after another, staccato — a lock or shield motif reinforces the theme without overstating (no "bank-grade" / "encrypted" language — the real claim is simpler and true: nothing leaves the machine).
- voiceover: "100% offline. / No account. / Nothing leaves your PC. / Nothing ever collected."
- duration: 6.229s
- transition_in: crossfade
- status: animated
- src: compositions/frames/03-security-stack.html
- type: benefit_highlight
- persuasion: Risk reversal
- beat: trust + relief
- blueprint: kinetic-type-beats
- asset_candidates:

narrativeRole: Backs the Frame 2 claim with concrete, checkable security proof before any feature talk starts — the video's security beat, per user direction.
keyMessage: The privacy claim isn't vague — it's four specific, verifiable facts about what never happens.

blueprint: kinetic-type-beats (Adapt — Benefits/staccato-montage variant, dramatized)
focal: (typography + a glowing shield glyph; no captured asset)
roles: (none — typography + one inline SVG icon drawn in Step 5, not a candidate asset)
sfx: none

Adapt: each phrase now lands inside a glass-card pill (translucent + glowing edge) with a quick glow-flash on arrival, not bare text on flat ground — staccato energy matching the VO's quick cadence.
Scene 1 (0.0–1.557s): hard cut from Frame 2's glowing lockup. Deep navy canvas, swirl field drifting; a glowing shield/lock badge (blue glow halo, gentle pulse) pops in dead-center-top via spring scale-in with overshoot — establishes the security register before any text.
Scene 2 (1.557–3.114s): as the VO says "100% offline," the phrase spring-pops into a glass-card pill below the glyph with a quick glow-flash, holds, then clears — one beat.
Scene 3 (3.114–4.671s): as the VO says "No account," the same slot spring-pops the next phrase, glow-flash, holds, clears.
Scene 4 (4.671–5.450s): as the VO says "Nothing leaves your PC," next phrase, faster cadence now, spring-pops with glow-flash, clears.
Scene 5 (5.450–6.229s): as the VO lands "Nothing ever collected," final phrase spring-pops with a stronger glow-flash and SETTLES — holds to the harness cut into Frame 4 (no further tumble/exit).

## Frame 4 — Feature grid

- scene: A four-tile card grid self-assembles, one tile per headline feature, each with its own simple icon badge.
- voiceover: "Voice to Text. / Cleaned Up Mode. / Auto Text and Dictionary. / Dictation History."
- duration: 5.163s
- transition_in: zoom-through
- status: animated
- src: compositions/frames/04-feature-grid.html
- type: feature_showcase
- persuasion: Feature-to-benefit translation
- beat: clarity + confidence
- blueprint: grid-card-assemble
- asset_candidates:

narrativeRole: Enumerates the product's real, named capabilities at once — the evidence layer beneath the value claim.
keyMessage: Talkative already does the things a dictation app needs to do, under its own real feature names.

blueprint: grid-card-assemble (Adapt — Key_Feature grid variant, dramatized)
focal: (typography + inline icon glyphs per card; no captured asset — glassmorphic badges, matching the new glow system)
roles: (none — no captured candidates; four in-scene icon+label tiles authored directly)
sfx: soft-pop ×4 (one per card arrival)

Adapt: keep the stagger-assemble-into-slot signature move and stretch the cascade across the full 5.163s duration (each tile on its own VO cue), but cards are now glassmorphic with glowing borders, each arrival gets a spring-pop + glow-flash (not a plain fade+slide), the traveling sweep uses the full blue→violet→pink gradient, and the closing camera push is more pronounced.
Scene 1 (0.0–1.147s): hard cut from Frame 3. Deep navy canvas, swirl field drifting; four empty glass-card slots (translucent fill, glowing edge, 24px radius) outlined in a row. As the VO says "Voice to Text," the first card's icon badge + label spring-pop into slot 1 with a glow-flash — real overshoot, not a soft fade.
Scene 2 (1.147–2.583s): as the VO says "Cleaned Up Mode," card 2 spring-pops into slot 2 the same way; card 1 rests with a gentle sine float, its glow edge pulsing softly.
Scene 3 (2.583–4.018s): as the VO says "Auto Text and Dictionary," card 3 spring-pops into slot 3; cards 1–2 continue their float, a full-gradient (blue→violet→pink) glow sweep travels once across the completed tiles.
Scene 4 (4.018–5.163s): as the VO lands "Dictation History," card 4 spring-pops into slot 4 with the strongest glow-flash yet, completing the 4-card row; a visible camera push-in (not subtle) begins under the completed grid and holds to the harness cut into Frame 5.

## Frame 5 — Same app, new name

- scene: A calm, near-still two-line title card: continuity reassurance.
- voiceover: "Same app. Same developer. / Now called Talkative."
- duration: 3.264s
- transition_in: blur-crossfade
- status: animated
- src: compositions/frames/05-same-app-new-name.html
- type: branding
- persuasion: Friction reduction
- beat: trust + ease
- blueprint: titlecard-reveal
- asset_candidates:

narrativeRole: Answers the one question an existing user would have mid-video — reassures nothing was lost in the rename — before the close.
keyMessage: The rename changes the name only; nothing about using it changes.

blueprint: titlecard-reveal (Adapt — Benefits variant, softly dramatized)
focal: (typography + the still-drifting swirl field)
roles: (none — pure typography beat, the video's deliberate breather per Video direction)
sfx: none

Adapt: this stays the video's one calm beat per the story's own pacing — but "calm" no longer means flat/static. The swirl field keeps drifting softly behind the type, and "Talkative" carries a light glow, so the frame reads as a quiet moment IN a living video, not a return to the old flat system.
Scene 1 (0.0–0.326s): blur-crossfade in from Frame 4's grid to the swirling navy canvas, blobs drifting slow and soft here (lower amplitude than other frames — this is the breather) — no busy open.
Scene 2 (0.326–1.632s): as the VO says "Same app. Same developer.," this line gently fades in centered (white, 95%→100% scale, smooth ease-out) and holds — the one restrained move, per the blueprint's contract.
Scene 3 (1.632–3.264s): as the VO lands "Now called Talkative.," the first line translates up and fades out while this qualifier line translates up from below-center and fades in — one slide-up crossfade, "Talkative" carrying a soft blue glow (not a hard pop — this frame stays gentle). Holds still to the harness cut into Frame 6.

## Frame 6 — Close

- scene: The app icon builds into a full lockup with the wordmark, the tagline settles beneath it, held.
- voiceover: "Talkative. / Just talk."
- duration: 1.557s
- transition_in: zoom-through
- status: animated
- src: compositions/frames/06-close.html
- type: cta
- persuasion: Memorable close — a two-word tagline distilling the whole promise (hold a key, speak) into an imperative the viewer can carry away; invented because no listed persuasion move names a closing-tagline beat specifically.
- beat: confidence
- blueprint: logo-assemble-lockup
- asset_candidates: assets/app-icon.png — Talkative's mic-on-squircle app icon, transparent PNG

narrativeRole: Terminal brand beat — the logo lockup is the last thing on screen, held long enough to register.
keyMessage: Talkative — hold a key, speak, done.

blueprint: logo-assemble-lockup (Adapt — Brand_Outro/parts-arrive → settled-reveal blend, this is the video's CLIMAX frame)
focal: assets/app-icon.png
roles: assets/app-icon.png = cutout (the mark, dead-center; wordmark + tagline build around it, dual-glow treatment)
sfx: soft-chime (on the mark's spring-bloom)

Adapt: this is the most visually alive frame in the video, not another calm hold. Keep the whole-mark spring-bloom-from-zero signature move, but the wordmark now carries its dual-color (blue+violet) signature glow, and gradient-stroked concentric rings (blue→violet→pink) sweep in behind it instead of flat thin lines — the swirl field flares brighter here, the climax, rather than fading out.
Scene 1 (0.0–0.374s): zoom-through hard cut in from Frame 5's calm. Swirl field flares brighter for this climax beat. As the VO says "Talkative," the app-icon mark spring-BLOOMS from zero at dead center with real overshoot + slight rotation-in + a bright glow-flash — the frame's hero move, compressed into one quick beat since the synced line is brief.
Scene 2 (0.374–0.778s): the icon slides a short distance up-and-left while the "Talkative" wordmark wipes in to its right carrying its dual-color glow (no letter-stagger — the window is too tight); gradient-stroked rings begin sweeping in behind the pair as it centers into a balanced lockup.
Scene 3 (0.778–1.557s): as the VO lands "Just talk.," a glowing tagline wipes in left→right beneath the lockup and settles. The completed lockup holds to the very last frame with the gradient rings still gently sweeping and the swirl field still visibly alive — the video's terminal beat, alive to the end, not frozen.
