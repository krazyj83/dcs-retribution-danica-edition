# Prototype Arbitrary Airdrop System

This is a minimal prototype for DCS Retribution.

## Features

- User-defined insertion point
- Arbitrary map coordinates
- Air assault compatible
- Transport mission compatible

## Example

```python
from game.logistics.custom_airdrop import create_custom_airdrop_target

# Example position object
position = some_position_object

# Create target
lz = create_custom_airdrop_target(
    "Test LZ",
    position,
    coalition="blue",
)
```

## Notes

This is only the initial prototype layer.

It does NOT yet include:
- UI integration
- persistence
- troop spawning
- CTLD
- dynamic logistics
