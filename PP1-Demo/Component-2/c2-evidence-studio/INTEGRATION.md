# Add C2 to the shared presentation frontend

This package integrates **presentation**, not the C1–C4 backend pipelines.
Every component may continue using its own runtime and local models.

## Option 1: embed the separate C2 page

Copy the complete `c2-evidence-studio/` directory into the shared app's public or
static directory, preserving the filenames and the `data/` directory.

Create one sidebar item named **Conflict resolver**. Render this iframe
when selected:

```html
<iframe
  src="/c2-evidence-studio/index.html?embedded=1"
  title="C2 Evidence Arbitration — recorded demonstration"
  style="width:100%;height:calc(100vh - 64px);border:0"
></iframe>
```

Adapt the URL to the shared application's static-file layout or base path.
This route requires no C2 backend. The iframe isolates its styles and controls.
The parent page and assets should be served by the same shared application.
The `embedded=1` option hides the C2 sidebar, so only the common app's sidebar
is visible. All C2 examples, memory playback and the expandable model comparison
are inside this one route. Opening `index.html` without this option retains a
standalone sidebar with the single Conflict resolver entry.

## Option 2: mount inside the common page

Load `styles.css`, then `data/recordings.js`, then `app.js`, using the correct
asset base path. Supply a host element and mount after the scripts are loaded:

```javascript
const instance = window.mountC2Studio(hostElement, {
  data: window.KEEL_C2_DEMO_DATA,
  caseId: 'flight',
  embedded: true
});

// When the host route unmounts:
instance.destroy();
```

Omit `data-c2-studio` on this manually mounted host element; that attribute is
reserved for automatic mounting in the standalone index page. Mount once per
host element. Call `destroy()` to remove its handlers and stop playback.
CSS selectors are scoped to `.c2-studio`; the standalone index's body sizing
does not need to be copied into the host app. Override `.c2-studio` height in
the host layout if the common application already has a header.

## Example IDs

`flight`, `stock`, `weather`, `unfamiliar`, `residence`, `time_scope`.

## Instructions for the integrating AI code agent

1. Keep the recordings and experimental results unchanged.
2. Add C2 as a sidebar route in the shared presentation shell.
3. Preserve the visible **Recorded replay** label.
4. Do not describe playback controls as live model inference or database writes.
5. Do not add fake drift, latency, token or live-session metrics to match the
   reference screenshot. Render only the recorded C2 evidence provided here.
6. Retain the source attributions and the collapsed evaluation details.
7. Test all six example selectors, Previous/Next/Play, the memory states and
   model-comparison values after integration.

## Important distinction

The existing live C2 viewer sets anti-embedding protections and depends on local
services. Do not remove those protections or embed that live service to make
this package work. This copied, self-contained presentation module is separate
and contains only the prerecorded examples needed by the shared frontend.
