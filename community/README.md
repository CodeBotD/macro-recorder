# Community macros

Share macros with other Macro Recorder users by opening a pull request that adds a JSON file to this folder.

## File format

Each file must be valid JSON with an `events` array (same event shapes the app records). Include `author` and `description` so the in-app Community mods browser can show them:

```json
{
  "author": "YourName",
  "description": "Short summary of what this macro does",
  "events": [
    { "dt": 0.0, "type": "key", "key": "char:a", "pressed": true },
    { "dt": 0.05, "type": "key", "key": "char:a", "pressed": false }
  ]
}
```

## Guidelines

- Use a clear filename ending in `.json` (for example `open-notepad.json`).
- Keep the description short and useful.
- Only include macros you are allowed to share.
- The app lists files from this folder on GitHub and only copies a macro into the user's library when they click **Add**.

## How users install

1. Open Macro Recorder.
2. Click **Community mods** (left of Settings).
3. Select a macro and click **Add**.
4. **Delete** removes it from the local library; it shows up in Community mods again.
