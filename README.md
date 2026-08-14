# structure Converter

turns a WorldEdit `.schem` file into a single string of Minecraft commands for mcsrranked

The commands are joined with `;`

## Quick start

```bash
python schem_to_commands.py input.schem
```

That opens a little menu by default where you can pick options like whether to clear the area first, where to place the structure, and so on. Your finished command string is saved to `output/input.txt`.

you can skip the menu:

```bash
python schem_to_commands.py input.schem --no-tui
```
If you would rather paste at a fixed world position, use absolute coordinates.

## Command-line options

| Option | what it does |
| --- | --- |
| `-o, --output PATH` | Save the `.txt` somewhere other than the default `output/` folder. |
| `--no-tui` | Skip the interactive menu and use flags only. |
| `--include-air` | Also place air blocks. Useful if you want the target area fully cleared before building. |
| `--no-merge` | Write one `setblock` per block instead of merging matching blocks into `fill` boxes. |
| `--slash` | Add a `/` in front of every command, so you can paste them straight into chat. |
| `--origin "X Y Z"` | Place the structure at a fixed world coordinate instead of relative to the player. |
| `--aggressive` | Strip out block-entity NBT and some transient block states to make the output shorter. |

### Examples

```bash
python schem_to_commands.py house.schem

python schem_to_commands.py house.schem --no-tui --include-air

python schem_to_commands.py house.schem --no-tui --origin "100 64 -200"

python schem_to_commands.py house.schem --no-tui --slash
```

## A few things worth knowing

- **Air is skipped by default.** Turn on `--include-air` if needed.
- **Block entities are handled.** Chests, signs, command blocks, and anything else with extra data geta `setblock` plus a `data merge block` command. That way inventories signs and command block contents survive.
- **Coordinates are relative to the player by default.** The tool reads the `Metadata.WEOffsetX/Y/Z` values WorldEdit stores in the `.schem` file, so the anchor point matches where you were standing when you copied the build.
- **Supported formats:** Sponge Schematic v1, v2, and v3.
