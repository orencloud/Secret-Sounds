# Secret Sounds

A Blender add-on by orencloud for customizable operation sounds. Supports Blender 4.5 LTS and later.

Install the latest Secret Sounds ZIP from [Releases](https://github.com/orencloud/Secret-Sounds/releases) using Blender’s **Preferences → Add-ons → Install from Disk**. Sound themes, clip previews, volume, and update settings are in the add-on’s preferences.

## Updates

The add-on checks GitHub in the background when Blender allows online access. Use the **Updates** section to check manually or install an available release. Restart Blender to finish the installation.

Managed updates preserve your current theme, custom clips, disabled cues, and intentionally empty clip lists. New bundled themes and sound triggers are added to your existing choices.

## Publishing a release

Set `bl_info["version"]` in `secret_sounds/__init__.py`, tag the matching commit as `vMAJOR.MINOR.PATCH`, and attach `secret_sounds.zip` to a stable GitHub release. The ZIP must contain the `secret_sounds/` package at its root. Keep existing bundled audio filenames for the same audio bytes, and use a new filename when adding audio.
