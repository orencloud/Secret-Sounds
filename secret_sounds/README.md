# Secret Sounds

Developed by orencloud. A standalone add-on for Blender 4.5 LTS and later on Windows and macOS.

Install the ZIP from Blender's Add-ons Preferences and enable **Secret Sounds**. All controls are in its Add-on Preferences. Use **Sound Themes** to search cues, preview clips, add random variants, and manage themes. Blender saves the configuration in its own preferences.

The first theme includes copies of the original MP3s and the starting volume, pitch, and speed values. The add-on uses local Blender preferences and its own packaged audio. It has no external application, setup script, or Unreal runtime dependency.

It observes Blender's native tools and keeps the existing keymap. The loop-cut target cue estimates the eligible ring on the active edit mesh. Playback tempo for motion loops uses cached bands and crossfades while pitch updates continuously. Some operations that are specific to another editor have no native Blender equivalent. Array Count and Array Spacing follow Blender's modifier controls.

References for native behavior
[Blender Loop Cut and Slide](https://docs.blender.org/manual/en/4.5/modeling/meshes/editing/edge/loopcut_slide.html)
[Blender Audio API](https://docs.blender.org/api/4.5/aud.html)
