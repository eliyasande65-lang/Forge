# CodeForge - mobile code editor (Python, JavaScript, HTML)

Kivy app, built into one APK for 64-bit (arm64-v8a) and 32-bit (armeabi-v7a) Android.

## Build the APK (GitHub Actions)
1. Create a GitHub repo and upload everything in this folder to the repo root
   (the `.github/workflows/build.yml` file must keep its folder path).
2. Open the repo's **Actions** tab. The build starts on push, or run
   "Build CodeForge APK" manually. First build takes about 20-40 minutes.
3. Download the `codeforge-apk` artifact, unzip it, install the `.apk`.

## Features
- Tabs, syntax highlighting, line numbers, current-line highlight
- Auto-indent, auto-close brackets/quotes and HTML tags, symbol bar, Tab key
- Find / replace, go to line, comment toggle, indent/outdent, duplicate line
- Run Python in-app (console, input() prompt, Stop button)
- Run HTML / JavaScript in a built-in WebView with a live console
- File browser (open, save as, new, rename, delete), dark and light themes
- Session restore: open tabs and unsaved drafts survive app restarts

## Notes
- Files live in the app workspace by default. To edit files elsewhere on
  your phone, open More > Settings > Grant all-files access.
- Python Stop interrupts at the next bytecode step (a long `time.sleep`
  finishes first).
- WebView: `alert()` is shown in the console; `prompt()` is unsupported.
