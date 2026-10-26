# Privacy and sharing snapshots

The inspector never uploads anything and never modifies a world. Everything runs locally.

## What a snapshot can contain

- World name, dimension names and block coordinates
- Machine types and machine state (progress, run times, stored fluids, ...)
- With `dump`: raw TileEntity NBT, which may include owner UUIDs, custom names and item data

## Sharing a snapshot in a bug report

That is often exactly what a maintainer needs, but strip what you do not want public:

- Prefer `show` / `scan --mte <type>` over `dump`; they expose only the machine fields.
- Remove or replace the world name if it is identifying.
- Review coordinates before posting: they reveal base layouts.
- `dump` output can contain owner UUIDs — do not post raw dumps without checking.

A useful minimal bug-report payload usually looks like:

```text
gtnh-inspect show --world ... --dim DIM --pos X,Y,Z --json
```

plus the game version (`GT 5.09.51.482`, pack `2.8.4`) and what you expected.
