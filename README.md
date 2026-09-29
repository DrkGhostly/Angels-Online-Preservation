# Angels Online — local server

**\*English** · [Español](README.es.md)\*

Reverse-engineered network protocol for **Angels Online** (IGG, shut down in
February 2026, client 8.5.1.0) and a server that speaks it, built from the client files and
from traffic captures.

This is not a complete emulator. It is the **documented protocol** plus a
server that goes as far as it goes: you can create a character, run the
tutorial, pick a class, fight monsters, level up, and buy and sell in shops.
What is missing is listed below, without sugarcoating.

Every protocol claim in here has a measurement behind it. Where something is
a guess, it says so.

---

## Actual state

**Works**

- Login, character creation, selection and deletion, saved to disk
- Entering the world, movement, changing maps, and floor teleport zones
- Angel Raphael's tutorial: picking a class, getting the gear, the transfer
- Inventory with **quantities**: consumables stack, and equipping, unequipping
  and moving between slots all report back per slot, the way the real server
  does
- Shops: buying **several items and several units in one go**, selling,
  splitting a stack and destroying one. Buy and sell prices come from
  `item.xml`, and the sale total matches the captured one to the gold
- Using consumables: potions and food restore HP and MP and spend one unit
- Stats computed from `item.xml` (gear actually adds up), including carry
  weight
- Combat: hitting and being hit, damage numbers, criticals, dual wield,
  attack effects, dying and reviving, loot, experience and skill experience
- Monsters: per-monster attack cadence, chasing, wandering, respawn, and
  bleed and stun effects
- **Telling monsters from NPCs does not rely on the `klass` byte alone.**
  The live server sends some monsters with the NPC marker 199 -- 88 spawns
  across eight maps, which ended up as friendly NPCs with no AI. The client's
  own data settles it: `npc.xml` runs from 1500 to 24893 and `monster.xml`
  from 1 to 23860, and they share **no id at all**, so above 1500 the answer
  is certain. Below 1500 the `klass` still decides, because `npc.xml` does not
  reach down there and the old Lyceum NPCs use two- and three-digit numbers
  that collide with `monster.xml`
- **255 maps populated from captures**: 42,860+ monsters, 2,350+ NPCs and
  15,059 map objects, 7,671 of them with their resource name resolved. Every
  monster, NPC and resource comes from a capture; none of it is made up
- **Twenty maps do not come from the main server, but from a second one**:
  three whole zones -- **Night City Code**, **Sun Sea Maze** and
  **Cybertronica** -- plus two Training Areas. It is the only exception to
  "everything comes from captures of one server", and it is explained below in
  _The three zones that came from elsewhere_
- **Whole zones are closed**, meaning every tornado in them has been crossed
  and measured: **Heart of Eden**, **Floating** (6 maps), **the desert ring**
  (Crescent Valley, Desert Racetrack, Ghost Village, Troop Outpost, Ancient
  Front, Fantastic Sand City, Nightmare Palace) and **Candyland** (7 maps).
  **Atlantis is complete except for the instances** (including the central city
  of **Palm Base**, populated with its 50 NPCs and 22 verified shops and services),
  and the forest chain
  (Cryptic Moon Swamp to Giant Wooden Stairs, 8 maps) only has two tornados
  left. Plus a good part of Pharaoh, East Orient and the four faction
  territories. The late-game chains added last are closed too: **Arcana**
  (Starglow Path, Academia Woods, Mana Ruins, Coo Village, Ethereal Garden,
  Daydream Library, Reminiscence Cloister), **Goldenia** (Emerald Coast to
  Royal Ruins, 9 maps), **Abyston** (Forsaken Crevasse, Specter Village,
  Crystal Marsh, Crystal Quarry, Shrouded Haven, Peril Chasm) and the deep
  chain from Galaxia Square to Deep Prison
- **572 portals**, 551 of them active, almost all measured in both directions: the tornado's tile
  comes from the capture, and so does the tile the real server drops you on.
  Most of them were crossed **twice in each direction**, which is how we found
  out that some portals do not always drop you on the same tile
- **Portals that lead somewhere else on the same map** work: **29 of them**,
  across seven maps. Lost Trail alone has twelve -- six pairs that move you
  from one end of the map to the other --, Horizon Archives has five and
  Branch Way has two pairs. They do **not**
  reload the map -- measured over 1,401 seconds without a single `0x000C`.
  The server answers `0x0016`, a `0x0012` of seven zeros and a `0x0003` that
  just moves the character
- **Portals can carry their own menu.** Teddy Amusement's hub asks "Move to
  which area?" and sends you to one of two spots on the same map. Each portal
  brings its own message id and its own option-to-tile table, so a new one is
  data, not code
- **15 more portals are recorded but switched off**: **fourteen instance
  entrances**, the one Lost Cove portal that was never measured, and the Niro
  River tornado to Clink Harbor -- that map exists in `stage.xml` but the
  live server has no content for it. The entrances were found by crossing
  the maps and cross-checking against the client's own `jumpmap.xml`, which
  labels them with **two different names**, `Instance Entry Point` and
  `Instance Entrance`
- **Angels GO!, the Superwing teleport**, works: `0x0151` carries the entry id
  from the client's own `jumpmap.xml`, a Superwing is spent, and the answer
  splits in two, both measured -- a `0x0003` when the destination is on the
  map you are already on, a `0x0007` plus `0x000C` when it is another map.
  The table has **355 destinations** and **224 of them are live**, the ones
  that land on a populated map; the rest are refused without spending the
  item. A character who does not belong to one of the four factions cannot
  use a Superwing at all -- measured on a level 12 still in "Heaven"
- The four faction cities with their arrival tile, all four measured: Aurora
  City, Breeze Woods, Iron Castle and Dark City. Picking a faction leaves you
  next to that city's Angel, three or four tiles away, in all four
- **The full leave-the-Lyceum flow**: the Angels' Tutor, choosing a faction at
  the Graduation Palace, travelling to your city, registering with its Angel
  and being sent back to the Lyceum. It works in **all four cities**, each
  with its own text, its own registration quest and its own follow-ups
- Portals between the Lyceum and both playgrounds, with their menus
- Cupid sets your revival point where you are standing
- Per-weapon attack animation and rhythm, measured: spear, staff, sword,
  dagger and dual wielding each send their own pair of values
- Skill cooldowns come from each skill's own data, separate from the basic
  attack rhythm
- Mages can swap a magic branch: the spells of the new branch are granted
  and the old branch's are dropped
- **Magic and skill system**: implemented combat and magic branches (Life,
  Wraith, Chaos, Earth, Curse, Meditate, Hit, Staff Hit, etc.) with initial
  spells, MP costs, and quick-bar assignments
- **Spell damage formula & scaling**: base damage computed from Spell Attack
  (SA) and spell multiplier minus target's effective Spell Defense (SD), plus
  elemental affinity modifiers (Fire, Ice, Thunder, Corrosion) and spell damage %
- **Cast times and reductions**: dynamic cast times read from `content.db`,
  supporting flat cast time reductions from active self-buffs (`First Path`,
  `Third Spirit`, `Limit Breaker`, `Shadow Meld`, `Killer Intent`) and the
  **50% cast reduction** from passive `Curse Spell` (ID 5)
- **Distinct casting animations**: magic spells play proper hand-casting
  animations and ground circle glyphs (`0x0011` byte 20 = 1) without triggering
  phantom dual-wield melee strikes (`0x000A`)
- **Level up visual banners (`0x0020`)**: cherub and trumpet animations (red
  banner for character level up, blue banner for skill level up)
- **Skill EXP progression**: leveling up skill ranks (up to level 300) through
  both physical and magical combat, distributing experience to active and class
  passive skills based on damage dealt
- **Dynamic Job / Class ID calculation**: automatic character Job ID
  determination based on currently equipped skill trees
- **Skill Scrolls & Books**: reading and learning new skills from scrolls
  found in `content.db`, fully persisting learned skills across sessions and
  map changes without losing them or reverting to `?`
- **Wraith Summoning System**: full implementation of minion invocations across
  all 11 families and 55 skills (Death's Head / Skeleton, Death Mummy, Death Leech,
  Azrael, Soul Eater / Muncher, Demon I-V, Demon Summon I-V, Ghostly Swordsman,
  Putridox, Minotaur, and Earth Titan / Golem). Features ground portal/coffer
  summon animations at target tile (`tx, ty`), minion entity spawning (`0x0008`),
  dedicated minion HP bar (`0x0013`), player-minion bidirectional binding links
  (`0x3c` and `0x3d`), autonomous combat AI, cross-map persistence (`0x000D`),
  and authentic attack cadence/speed calibration
- **Ground & Self Area of Effect (AoE)**: execution of ground-targeted and
  self-centered AoE spells (Strong Acid Rain, Hell Flame, Frozen Trap, Fire Trap,
  Thunder Scope, etc.) on any valid tile without requiring an enemy target,
  with ground glyph and impact visuals (`0x0011`)
- **Ring of Angel Wings**: teleportation back to the Cupid revival checkpoint
- **Expanded NPC Dialogues & Official Shops**: dynamic dialogue, quest interactions,
  and verified vendor shops across faction cities, regional hubs, and dungeons:
  - **Palm Base (Stage 88 - Atlantis)**: all 50 NPCs populated with exact dialogues,
    sprites, and 22 verified shops/services (level 80-90 skill trainers/deputies,
    bowset & weapon sellers, high-level smith/master recipes, stuffshops, craft clerks,
    native equipment repair, warehouse bankclerks, and pet services)
  - **Lava Cave (Stage 69) & Flaming Door (Stage 70)**: level 60-70 smith and master
    crafting recipes (Rock Smith & Rock Master), advanced weapon and bow researchers,
    and magic trainers (Earth Life Mage & ChaosWraith Mage)
  - **Faction Hubs & Outposts**: Cherry Village, Memory Cave, Mysterious Garden,
    Gebuer Vale, Dragon Graveyard, Mysterious Wetland, etc.

**Partly**

- NPC dialogue: 17 of the Lyceum's 52 NPCs have their text and options, plus
  expansion to regional and dungeon skill vendors
- **Skills and spells**: melee combat, AoE spells, and magic trees are operational
  (casting, costs, damage, buffs, debuffs, summons, and progression). Longbow
  and dagger have received less testing
- Spells: they show up on F1-F3, cast, buff and deal damage, but some visual
  effects are still missing
- Physical and spell damage formulas now scale with linear defense mitigation
  and elemental stats, though extreme high levels (300+) or monsters with outlier
  attributes may still need fine calibration against packet captures
- Pets: can be equipped and show their world sprite, but autonomous pet combat AI
  and automatic feeding systems are still in development
- Combos are read from `magic.xml` but never executed
- The slow effect is registered but doesn't change movement speed
- The staff and the axe use the sword's attack animation until someone
  captures theirs
- Mounts equip to slot 10 and do speed you up, but not by the right amount:
  two different mounts that declare the same `move_speed` give different
  speeds in the real server, so what a mount contributes depends on its own
  instance, and that doesn't travel in `item.xml`

**Does not work**

- The ID Card draws the character in their underwear, even though the sprite
  in the world is dressed correctly (see below)
- Resources can't be gathered, so the nine skills tied to gathering and
  crafting never level up
- Five of the Lyceum's NPCs were never captured and are missing
- Passwords are **not validated**: the auth block hasn't been decrypted
- Quests and whether you have spoken to Michael are **not saved to disk**:
  they survive the session and are lost on reconnect
- The diving gate is **documented but not enforced**: both trainers, their
  dialogue and the two skills are captured, but the portal into the
  underwater maps still lets anyone through
- Instances: nobody has been inside any of them. **Five entrances are
  identified and left switched off** -- Nightmare Palace, Half-beast Hamlet,
  Giant Wooden Stairs (which has two tornados leading to the same place) and
  Chocolate Forest. They sit in `portales.json` with their tile and their
  entity but with a null destination, and the server skips them, so standing
  on one does nothing. For Lost Region and Horrible Lost Region the entry
  dialogue, the two modes and the rejection messages are captured; their
  monsters are known from the wiki, their positions are not. Careful with one
  thing: that two-mode dialogue is **not** how instances are entered in
  general -- most ask nothing at all
- Parties and the friend list: the protocol is documented from a two-account
  capture, but the server does not implement either yet

---

## The item catalogue

[`items.html`](items.html) is a single page listing **78,089 items** -- every
one in the client data, with its **id**, name, kind, group and icon. It is
built from the extracted client (UPDATE25) and from `corpus/content.db`, and
it needs no server and no connection: open the file and search.

It exists because the id is the one thing you cannot guess. The game never
shows it, and the tooling that hands out items takes the id and nothing else,
so anyone helping with drops, shops or testing ends up asking for the same
numbers over and over. This puts them all in one place.

The page weighs about 19 MB because the whole catalogue travels inside it, as
a JSON array the page filters in the browser. That is on purpose: a single
file that works offline is worth more here than a smaller one that needs
something running behind it.

`GM_ITEM_COMMAND_FOR_AI.md` is the spec for the in-game command that would use
those ids, written to be handed to an AI. **It is not implemented yet**: the
file describes what to reuse from `app.py` and how the command should parse,
and the server still has none of it.

---

## The three zones that came from elsewhere

Everything else in this project comes from captures of **a single** private
server. Twenty maps do not. They come from **a second server, on another
version of the client**, and it is worth knowing why and what it implies:

- **Night City Code**, stages 416 to 421 -- Clink Harbor, Neon Sky Corridor,
  Black Market District, Commercial Street, Bling Plaza and Ultimate Arena
- **Sun Sea Maze**, stages 397 to 402 -- Floating Station, Floral Alley,
  Majestic Mansion, Warm Villa, Verdant Shrine and Seaside Grotto
- **Cybertronica**, stages 405 to 410 -- Sandy Heights, Wise Institute, Clank
  Oasis, Ironbone Works, Machinery Ruins and Steely Circuit
- **Training Area A and B**, stages 118 and 134

The three zones share the same reason, told below with Night City Code
because that is where it was found first: on the main server the stages exist
but arrive empty. Seaside Grotto brought something extra, a teleport that is
not a portal: you **talk** to a statue and it moves you across the map. That
mechanism is described further down.

### Why another server was needed

The map had been in the client data since patch 25, and a tornado in Niro
River led to it. But crossing it, the server sent **7 entities and nothing
else**, all NPCs, all bunched in the (1..6, 1..5) corner. That is the
signature of a stage **declared but not populated**: it exists in the table,
it has no content. The portal sat measured but disabled, with a note saying
"enable it when some version brings the map populated".

The second server runs that version. Crossing the same tornado, it sends
**171 entities** spread across the whole map, with real monsters.
The map exists; what was missing was a server that served it.

### What was taken and what was not

The standing rule still holds: **take the DATA, never the raw bytes**. It
worked here because both speak the same language where it matters -- the
`0x0008` spawn message is **63 bytes in both versions**, with the fields in
the same places, and so is `MOVE_REQ`. The same code decodes it.

Where they do **not** match, and it needs keeping in mind:

- The `0x000C` map change arrives as **20 bytes with no IP string**, unlike
  ours. The stage still reads at offset 0, but the destination port is no
  longer where we expect it
- **Three messages we do not know** show up: `0x018A`, frequent and almost
  always eight bytes; `0x006D`, with an empty body; and `0x0142`, a single
  byte. None of them are in `proto/messages.py`

Names arrive in **Big5**, not English. Nothing had to be translated by hand:
the `npc_type` is the same in both versions, and our `content.db`, extracted
from the client XMLs, already carries the English name for every id. They are
matched through that.

### Two things that changed in the tools

**`tools/separar_por_mapa.py`** (new). On the other server every map change
opened a fresh connection, so each capture file covered a single map. Here the
`0x000C` arrives **inside the same session**: one connection brought six maps
in a row. Handing it whole to `poblar_mapa.py` would put one map's monsters
into another map's template, silently. This tool cuts by map change first.

**`tools/poblar_mapa.py`** decoded names as ASCII, which mangles Big5. It now
decodes Big5 -- ASCII-compatible, so nothing earlier changes -- and matches the
`npc_type` against `content.db` to leave the name in English.

### What was learned along the way

**Some map transitions have no tornado.** Five of the chain's thirteen portals
have no drawn object at all: you walk onto the tile and the map changes, with
nothing visible. Confirmed both in game and in the capture, where no object
sits anywhere near. **What triggers it is unknown**; it could be an invisible
portal. They were first called "edge crossings" and that was a wrong guess:
the maps are 300x180 and those tiles sit some eight columns short of the edge,
with entities even further out.

**A map can need several passes.** Commercial Street gave 71 monsters on the
first walk, 109 on the second and 125 on the third. The map did not change: a
capture only brings what you had in view, and the early passes left areas
uncovered.

**A teleport that is not a portal.** In Seaside Grotto you do not walk onto a
tornado: you **talk** to a statue. The click arrives as `0x0005`, the server
answers a `0x0012` dialogue with two options, the client sends `0x000B` with
`0a` -- option index 0, "Yes" -- and then comes a bare `0x0003` that moves the
character. No `0x000C`, so the map never reloads. It cost two wrong readings:
first the `0x000F` right after the dialogue was blamed, and that one turns up
95 times per session because it is a heartbeat. The way back is not a click at
all -- you step on the tornado -- and it sends only the `0x0003`, without the
`0x0016` and `0x0012` that the internal jumps of other maps carry.

### What is still missing from this region

Stage **422 (Secret Peak)** is still unpopulated. There is also Bling Plaza's
**instance entrance**, identified through `jumpmap.xml` -- it is the only one
of the chain's nine destinations carrying an extra class -- and **three
tornados in Ultimate Arena** that would not let the player through, most
likely gated by a quest or a level.

---

## Running it

You need **Python 3.10 or newer** and the Angels Online client installed.
Tested against client **8.5.1.0**; the captures the protocol comes from were
taken with an **8.6.0.8**, and both speak the same thing.

IGG took the game down in February 2026, so the client is no longer available
from them. This is the copy this project is developed and tested against:

**[Angels Online client 8.5.1.0](https://drive.google.com/file/d/13IOcTJUkX7LfsznZ8tobyu5c5MuXjpZK/view?usp=sharing)**

It is IGG's client, unmodified. It is here because a protocol you cannot run
against anything is not much use, and because without it none of the
measurements in this repository can be reproduced.

1. Point the client at your machine, in its `server.xml`:

   ```xml
   <伺服器 名稱="Local" 編號="16" 選擇="100"
           ip="127.0.0.1" port="16768" 分流="2"
           fip="127.0.0.1" fport="21238" />
   ```

2. Start the server:

   ```
   ./correr_servidor.sh        # Linux, macOS, Git Bash
   correr_servidor.bat         # Windows
   ```

3. Open the client and log in with any username. The account is created for
   you.

Every session is recorded under `logs/sesiones/`, which is what you use to
debug.

### Environment variables

| Variable                | What it does                                                 |
| ----------------------- | ------------------------------------------------------------ |
| `AO_TILE`               | Spawn tile in Guide Palace (default `82,83`)                 |
| `AO_TILE_LYCEUM`        | Spawn tile in the Lyceum (`152,74`)                          |
| `AO_DURABILIDAD`        | Multiplies the durability of everything the server hands out |
| `AO_SECUENCIA_COMPLETA` | Sends the whole captured entry sequence, for comparison      |

---

## Layout

```
proto/        the protocol: framing, ciphers, message codec, LZO
server/       the server: login, world, inventory, combat, dialogue
server/plantillas/   blocks measured from real traffic, as JSON
tools/        capture proxy and analysis tools
docs/         everything that was worked out, and how it was verified
```

**Read `docs/01_HECHOS_VERIFICADOS.md` before touching anything.** It is over two thousand
lines covering every finding, how it was checked, and the mistakes made along
the way with their diagnosis. That last part is worth more than the code:
several things were taken as true from a single sample and turned out to be
wrong.

The documentation is in Spanish. The code and the commit history are too.

---

## The four tables that were hiding in the client

Four systems were guessed at for days before the data turned up inside the
client's own `.pak` files. None of them needed a formula: they are tables,
and the guesses were all wrong.

**`adv.xml` -- what the green hammer can give.** 2645 rows, by part and
level, with a floor and a ceiling for every stat. Two formulas had been
fitted to screenshots before this and both were wrong; what killed them was
using the same hammer on two pieces and getting different ranges. The table
matches the game exactly: a level 300 staff offers HP 344, attack 2428,
spell attack 697 and agility 30 -- which is what the client's own preview
box showed. It also settles the shape of the thing: a weapon never rolls
defence, armour never rolls attack, only a mount rolls movement speed, and
only a backpack rolls carry weight and extra slots.

**`pet.xml` -- 1751 pets.** Sprite, type id, name, which `petattrib` class
its stats come from, its evolution stage and its two branches. The type id
was going out as zero, and without it the client cannot tell which pet it is
looking at: the window came up with no level and no picture. The thirteen
sprite/type pairs seen in captures all match.

**`petaspect.xml` -- the breeding scenes.** 107 of them, three options each,
worth between -3 and +3. The text matches the game word for word.

**`jeweleffect.xml` -- what a gem does.** 870 rows. The numbers live on the
gem itself and this table says which stat they land on, and that depends on
where the gem is set: the same rune gives spell attack in a weapon and spell
defence in armour.

## Known issues

### The pet's own record is not saved

Everything else about pets works: the 231-byte inventory entry, the window
with its real stats, summoning and putting away, renaming, experience,
levelling and the whole evolution tree. But the pet's record lives only in
memory, so it resets to level 1 on every reconnect. The bag item persists;
what the pet has become does not.

### The breeding counter cannot be read

When a pet levels up the client shows a scene with three options and says
"(Your act affects Pet's growth)". That text is not sent over the wire: the
client picks the scene from its own `petaspect.xml` and only the chosen
option travels back, in `c2s 0x003E` with the values 4, 5 and 6 -- the same
message that carries pet orders with 0, 1 and 2.

So the server never learns which scene the player answered, and therefore
cannot tell what the answer was worth. Each of the 107 scenes has its own
three values, from -3 to +3. To close this the server has to pick the scene
itself and remember it, instead of letting the client choose.

### The ID Card draws the character undressed

The sprite walking around the world wears its gear correctly, but the figure
inside the ID Card panel shows the character in their underwear. The weapon
and the boots _are_ drawn there; it is the body garment that never applies.

Three candidates were ruled out by measurement, so nobody needs to repeat
them: `0x0149` is byte-for-byte identical every single time, `0x0179` comes
out the same after every equip regardless of what you put on, and the
character record `0x0002` contains none of the equipped item ids — two logins
of the _same_ character with different gear differ in only 56 bytes, all of
them stats and level.

What would settle it is a capture taken with the ID Card **open** while
taking a body garment off and putting it back on.

### The damage formula drifts at high level

`attack x 33 / (33 + defence)` matches what a low-level character does. At
level 118 it is off by a factor of about 75. The relationship turned out to
be linear in defence rather than multiplicative, with a slope that depends on
the levels involved, and there aren't enough samples across level ranges to
pin it down.

### The staff and the axe attack animations

The `0x000A` carries a type and an animation number, and the pair depends on
the weapon. Measured by following the equipment changes inside each session:

| weapon                 | type | animation |
| ---------------------- | ---- | --------- |
| sword, dagger          | 3    | 1480      |
| spear                  | 2    | 827       |
| staff                  | 2    | 951       |
| two one-handed weapons | 2    | 832       |

The number is not a duration: the spear swings slower than the sword and yet
its number is lower. It selects which animation the client plays, so sending
the wrong one makes a spear attack as if it were dual wielding, with the
weapon not drawn at all. The staff and the axe still fall back to the sword's
pair, so a capture of someone attacking with them would finish the table.

### Screenshots of issues since fixed

The images under `docs/capturas/` are kept as a record. All five have been
resolved: the skill panel and the F1-F3 spells, NPC dialogue and movement,
opening boxes, the shop, and the floor teleport zones.

---

## What is deliberately skipped

So the server runs without a database or a sign-up flow, some things aren't
checked. These aren't bugs, they're decisions:

**Accounts create themselves.** Log in with any username and it gets saved to
`data/cuentas.json`. If you want to set one up by hand, it's plain JSON:

```json
{
  "cuentas": {
    "youruser": {
      "password": "whatever",
      "personajes": []
    }
  }
}
```

**Passwords are NOT validated.** Anything gets you in. The username is read
from the auth message, but the block carrying the password hasn't been
decrypted, so there's nothing to compare against. Finding that field was tried
twice and both attempts were wrong: one rejected valid logins, the other
accepted everything because the offset turned out to be a client-side
constant. It's documented in `server/cuentas.py`.

**There's no sign-up, no email, no recovery.** It's a local server.

### Visual glitches on reconnect

Some things look wrong until you log out and back in. Server and client end up
agreeing, but the client doesn't refresh on the spot:

- Music cuts out when changing maps
- The gear panel can be left with an extra slot drawn

Nothing gets corrupted: what's in `data/cuentas.json` is always correct.

---

## How to help

What's missing most isn't programming: it's **captures**.

Almost everything that doesn't work is missing because it was never recorded.
The proxy sits between the client and a working server, and logs both
directions with timestamps:

```
python tools/proxy.py --server-xml "path/to/server.xml"
# play for a while, doing whatever you want to capture
python tools/proxy.py --server-xml "path/to/server.xml" --restaurar
python tools/correlacionar.py --novedades
```

Two lessons that took several rounds to learn:

- **A capture only contains what you had on screen.** To populate a map you
  have to walk all of it, not stand in one spot.
- **Leave a couple of seconds between actions.** If they pile up, there's no
  way to tell which reply belongs to which request.

What would help right now, most useful first:

1. **Equipping a body garment with the ID Card open**, so the message that
   redraws the figure can be isolated.
2. **Picking dialogue options** on several different NPCs. Five or six cases
   would fill in the 35 Lyceum NPCs that still have no text.
3. **Gathering a resource** with the right tool equipped. Nine skills depend
   on it and none of them can level up today.
4. **A long fight against monsters of several different levels**, with the
   levels of both sides written down, to pin the damage formula.
5. **Attacking with a staff and with an axe**, to finish the table of attack
   animations (sword, spear and dual wielding are already measured).

### Any kind of help

Everything is useful, and you don't need to know reverse engineering:

- **Traffic captures.** This is what's missing most. See above.
- **Code.** Pull requests are welcome. If you touch the protocol, say what you
  checked it against: this project rests on every claim having its
  verification behind it.
- **Client data.** If you find something in the `.xml` or `.pak` files that was
  written off as impossible here, say so. It has already happened twice that
  the data was right there.
- **Bug reports.** The server log plus what you did in the client is enough.
  The `logs/sesiones/` folder from that session helps a lot if you can share it.
- **Translations.** The documentation is in Spanish.
- **Just playing and telling us what breaks.** Half an hour in-game finds
  things that reading the code doesn't.

If you don't know where to start, open an issue and ask.

Before recording anything, check whether the data is already in the client's
XML files. It happened twice: spawn points were in `jumpmap.xml` and dialogue
in `msg.xml`, and captures were requested for things already on disk.

---

## Credits

This server was written from scratch, but it didn't start from nothing.

- **[AngelsOnlineDev/AO](https://github.com/AngelsOnlineDev/AO)** — the project
  that opened the way. No code was copied from it, but it was studied, and
  reading its log produced the finding that unblocked this whole project: the
  world redirect is sent **in reply to `0x0006`**, not after authentication.
  Weeks were spent stuck on that screen comparing bytes that were already
  correct; the problem was timing, not content.
- **Squirrel**, from RageZone — for trying first and leaving a trail. Someone
  having started and written something down, even without finishing, saves you
  the work of finding out which doors aren't worth opening.

And to whoever kept the client and its `.pak` files around. Without them there
would be nothing to rebuild: a good part of what works here came from reading
the game's own `.xml` files, not from traffic.

---

## Notice

Angels Online belongs to IGG. This is preservation work on a game that no
longer exists, done against a client anyone can install.

**Nothing of IGG's is included here**: not the client, not its data, not the
decompiled binary. The server reads the `.xml` and `.pak` files from a client
you already have; without one it does nothing and is of no use.

**No traffic captures are included either.** The ones used carried account
names and other people's public chat. The analysis lives in `docs/`; the raw
bytes aren't needed for anything. If you contribute captures, check the same
before uploading them.
