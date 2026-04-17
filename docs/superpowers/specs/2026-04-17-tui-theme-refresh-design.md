# TUI Theme Refresh Design

## Scope

This design updates the Aptgent TUI visual system around the existing `/theme` command and built-in theme picker.

The change is explicitly limited to:

- replacing the current theme preset list with three new presets
- updating the Textual theme definitions and shared chat styling
- enforcing a clearer chat lane model:
  - user messages on the right
  - system messages on the left
  - tool output visually distinct from normal system output
  - activity / breathing status visually distinct from both

This design does **not** introduce:

- a new theme switching mechanism
- workflow or step-order changes
- new subprocess or adapter behavior
- LLM behavior changes

## Final Theme Set

The existing theme preset list will be replaced with exactly three presets:

1. `clear-lanes`
2. `clean-minimal-light`
3. `warm-industrial`

The old presets such as `aptgent-dark`, `textual-dark`, `tokyo-night`, `gruvbox`, and `rose-pine-dawn` will be removed from the user-facing `/theme` picker for this branch.

## Theme Intent

### 1. Clear Lanes

Default dark operational theme with strong left/right chat lane separation.

Visual intent:

- near-black or deep slate shell
- cool blue system emphasis
- clearly narrower right-side user bubbles
- muted tool styling that reads like telemetry rather than dialogue
- amber activity state for the breathing/status bubble

This is the baseline "serious dark theme" and should be the default theme on app launch.

### 2. Clean Minimal Light

A bright, low-noise light theme focused on legibility and long-session comfort.

Visual intent:

- soft white / light gray shell
- restrained blue structural accents
- low-glare surfaces
- tool output separated by structure and border treatment rather than loud color
- amber activity state retained for consistency

This theme should feel clean and expensive rather than soft or playful.

### 3. Warm Industrial

A dark warm theme that feels instrument-like rather than cyberpunk.

Visual intent:

- charcoal / umber shell
- amber-led emphasis
- teal used as computational contrast color
- tool output shifted toward cooler patina/teal signals
- activity state in lighter amber/champagne

This theme should feel tactile and custom, with obvious distance from common blue SaaS palettes.

## Chat Lane Rules

These rules apply across all three themes.

### User messages

- always appear on the right side
- use a narrower max width than the current nearly full-width presentation
- keep right-edge emphasis, not left-edge emphasis
- remain visually readable for short and long messages

The goal is to make the user's voice read as a distinct response lane rather than a full-width block with right-aligned text.

### System messages

- always appear on the left side
- use the primary conversational surface for the active theme
- remain the most readable container for instructional and step text

### Tool messages

- remain on the left side with system output
- must be visually distinct from standard system bubbles
- should read as machine output / telemetry / side-channel information

Acceptable distinction mechanisms include:

- alternate border treatment
- cooler or more muted panel tone
- different label treatment
- lower visual priority than primary system guidance

Tool messages should not look like errors or warnings by default.

### Activity bubble

- remains on the left side at the end of the chat log
- uses a dedicated accent color separate from both normal system and tool states
- should remain visually noticeable while processing, but not overpower the log

The selected cross-theme intent is an amber-family activity signal.

## Widget-Level Styling Targets

The implementation should update styling in the existing TUI layers only:

- `aptgent/aptgent/tui/app.py`
- `aptgent/aptgent/tui/commands.py`
- `aptgent/aptgent/tui/styles/main.tcss`
- `aptgent/aptgent/tui/widgets/chat_widgets.py`
- tests affected by theme names or lane styling assumptions

Expected styling work:

- define three concrete Textual themes
- update `DEFAULT_THEME` to `clear-lanes`
- replace `THEME_PRESETS` entries with the new three-theme list
- align bubble widths, margins, borders, and color tokens to enforce left/right lane separation
- give `SystemBubble`, `StreamingBubble`, `UserBubble`, `ActivityBubble`, and tool-bubble styling clearer visual roles
- update breathing-frame colors if they currently conflict with the new activity/system/tool scheme

## Testing

At minimum, verification should cover:

- the welcome screen still starts with the default theme
- `/theme` or theme picker only exposes the new three presets
- the app can still switch themes without errors
- chat widgets still render and mount correctly in tests after style and preset changes

Visual behavior should also be sanity-checked in a live TUI session because the main change is presentational.

## Risks

### Over-styling

If theme accents are too strong, tool and activity states may compete with primary workflow content. The implementation should preserve hierarchy before spectacle.

### Light-theme regressions

The light theme can easily become washed out or low-contrast in terminal rendering. Contrast needs live verification, not just static token selection.

### Token drift between Theme and TCSS

The current UI mixes Textual theme tokens with hard-coded TCSS colors. The implementation should reduce contradictions so each preset produces a coherent result instead of a theme token being overridden by unrelated fixed hex values.

## Acceptance Criteria

The work is complete when:

1. the app launches with `clear-lanes` as the default theme
2. the theme picker and `/theme` command expose only `Clear Lanes`, `Clean Minimal Light`, and `Warm Industrial`
3. user messages are clearly right-lane bubbles
4. system output is clearly left-lane output
5. tool messages are visibly distinct from standard system messages
6. the activity bubble uses a separate visual signal from both system and tool output
7. existing TUI tests pass or are updated to the new theme list and behavior
