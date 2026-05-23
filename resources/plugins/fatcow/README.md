# FATCOW Plugin for DCS Retribution

AI-controlled CH-47 Forward Arming & Refueling Point (FARP) script by Don Rudi/C. Gurk.
Patched (v1.0.5.2) for CTLD compatibility by removing marker keyword collision and adding
a pcall-protected event handler.

## How it works

A player places a map marker with the text `##FATCOW` on the F10 map.
A CH-47 spawns ~10nm away and flies to the marker location to land and erect a FARP,
including fuel, ammo, infantry, and a MANPAD for local air defence.
The FARP is active for a configurable duration then despawns.

## CTLD compatibility

The original script used `FATCOW` as its map marker keyword, which could collide with
CTLD's own `S_EVENT_MARK_CHANGE` handler. This patched version uses `##FATCOW` instead,
which CTLD ignores, and wraps the event handler in pcall for resilience.

## Installation

1. Copy the `resources/plugins/fatcow/` folder into your DCS Retribution installation.
2. Add `"fatcow"` to your `resources/plugins/plugins.json` list (see below).
3. Enable the plugin in Retribution's **Settings → LUA Plugins** before generating a mission.

### plugins.json entry

```json
"fatcow"
```

Add it after `"ctld"` so CTLD loads first:

```json
["base", "ctld", "fatcow", ...]
```

## Usage in-game

- Open the F10 map
- Place a marker and type `##FATCOW` as the text
- Wait for the CH-47 to arrive and land (~10nm transit + erect delay)
- A FARP with fuel, weapons, infantry, and MANPAD will deploy around it
