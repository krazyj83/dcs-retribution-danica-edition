Supply transport tiers v2  (replaces the earlier "Supply transport tiers" folder)
Upload AFTER "Fix 5 Warehouse transfers". Commit to dev, overwriting files.

REDFOR: <120 km road convoy (if road-linked), 120-220 km helicopter airlift,
>220 km plane airlift. BLUEFOR: warehouse transfers are flown by a player-picked
squadron (Transfers tab -> "Flown by"), 1 aircraft, player seat.

If you already uploaded the first "Supply transport tiers" folder, also DELETE:
    game/missiongenerator/supplyconvoygenerator.py
(The coalition/debriefing/unitmap/QWaiting files here put those back to the Fix 5 version.)
If you never uploaded it, those four files are unchanged from Fix 5 - uploading them is harmless.
