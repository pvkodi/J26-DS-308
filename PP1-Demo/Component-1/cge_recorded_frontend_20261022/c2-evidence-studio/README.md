# C2 Evidence Studio — portable recorded demonstration

This is a separate presentation frontend inspired by the supplied CGE Studio
reference: persistent left navigation, a slim playback toolbar, pale background,
white inspection cards and compact tables. The original C2 demo was not changed.

## Open it

Double-click `index.html` in a normal browser. All data is bundled in JavaScript,
so this works without fetch requests, model weights, Python packages or Neo4j.

Alternatively, if Python is installed:

```powershell
python serve.py --port 8892
```

Then open `http://127.0.0.1:8892/`. Stop the server with Ctrl+C.

## One Conflict resolver page

- **Structured examples:** six steps through original reports, normalized candidates,
  stored features, saved ranking, checked contract and the available saved commit.
- **Conversational examples:** turn-by-turn residence and time-scope examples. Earlier turns
  only display the earlier visible claims and decisions from the source recording.
- **Expandable model comparison:** the seven saved methods on 6,206 structured TEST groups.
  Domain results and evaluation scope are retained in a collapsed section.

Choose a case in the toolbar. Previous, Next, Play and the
slider reveal existing recorded steps; they never execute a model.
All examples and results are on this single page. For a shared frontend, use
`index.html?embedded=1` to hide the standalone sidebar and place the module
inside the common app's **Conflict resolver** tab. See `INTEGRATION.md`.

## What the package actually does

- Replays saved structured predictions and conversation states.
- Displays recorded model utilities and source-support information.
- Displays an earlier successful Neo4j commit where a matching saved session was
  available. If no commit was available, it explicitly shows a preview instead.
- Displays historical graph IDs for inspection on the original database laptop.
- Uses no external JavaScript libraries, fonts, APIs or CDNs.

It does **not** train, run LightGBM or Qwen, connect to Neo4j, or change memory.
The common frontend can therefore run on the presentation laptop without GPUs
or the individual component services. Use the existing live C2 demo on its
configured laptop if the panel requests a fresh backend run.

The structured cases are known presentation examples, not fresh test samples.
The unfamiliar-provider case is an authored guard check. Saved model-comparison
results are separate evaluation evidence. Structured accuracy is not general
conversational accuracy. Utilities are not calibrated truth probabilities.

## Included files

```text
c2-evidence-studio/
  index.html
  app.js
  styles.css
  data/recordings.js
  serve.py
  README.md
  INTEGRATION.md
  MANIFEST.json
```

No virtual environment, credentials, raw archives, weights, local databases or
execution logs are included. `MANIFEST.json` identifies the source artifacts,
records the C3 UI review and hashes the portable files.
