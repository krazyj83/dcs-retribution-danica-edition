"""Living world: the campaign's era and terrain shape what can be bought and
where units stand.

- era.py: units can only be bought once they are in service at the current
  campaign date (their "introduced" year in resources/units).
- theaterperiod.py: the period each map depicts, for the New Game wizard.
- terrain.py: what the mission script needs to keep ground units off steep
  slopes, out of town centres and off roads (towns read from the player's
  DCS install).
"""
