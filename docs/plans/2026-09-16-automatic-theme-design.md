# Automatic management theme

The management interface offers Automatic, Light, and Dark. Automatic is the
default when no preference has been saved and follows the browser's system
color scheme, including changes while the page is open. Explicit Light and Dark
preferences remain in effect. The legacy `paper` value appears as Light.

Use the existing `system` API value and preferences CAS save flow. GET and PATCH
responses expose the default without rewriting stored preferences or advancing
the generation on reads. Only a successful save changes the applied theme.

A CSS `prefers-color-scheme` rule applies the existing dark palette to Automatic
and to the initial page before preferences load. This avoids a JavaScript media
listener and uses the same native color scheme for browser controls. Static
reader templates and immutable published artifacts keep their existing behavior.

Implementation: expose the default in the API, extend the frontend preference
type and selector, apply the CSS rule, then verify the frontend build and unit
suite plus desktop/mobile browser behavior. Browser checks cover both system
themes, live changes, manual overrides, saving/reloading, legacy `paper`, and a
rejected save retaining the applied theme. API verification covers default
responses, saved values, and unchanged read generations.
