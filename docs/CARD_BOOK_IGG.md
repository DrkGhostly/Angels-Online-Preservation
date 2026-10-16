# Card Book (Alt+C), IGG

Repair scope: `server/cartas.py`, Card Book packet routes in `server/app.py`,
its two bitmap fields in `server/login.py`, and atomic persistence in
`server/cuentas.py`. Shared inventory, combat, quests and movement helpers
are unchanged. `plantillas/cardsets.json` contains the 106 sets from the
installed update25 `setting/eng/cardset.xml`; the existing 459-card catalog
remains the source of card metadata.

## Evidence

Client: `G:/Angel.exe`, SHA256
`7C1F8CC16E2032081DC15CCC1A67DE66803F62D8252AB570D1F4724C162D6E9B`.
Sources: existing `Angel_unpacked.c`, `extracted_luas/card.lua`, selected
instructions of the supplied unpacked PE, and the current XML/catalog DB.
This is static evidence, not a claim of a successful in-game test.

| Operation | Client routine | Wire layout |
|---|---|---|
| Register card | Lua wrapper 00596340 -> 0061B000(slot,0) | C2S 002E `<BI slot,0>`; slot >255 uses 0132 `<II slot,0>` |
| Exchange set | wrapper 00595C90 -> 006229C0 | C2S 0130 `<BB set_id,choice>`; choice 0/1/2, or FF for all |
| Update membership | 005F0EF0 -> 0060D5A0 | S2C 001D `<IB entity_id,count>` then `<BII kind=27,card_id,operation>` |
| Mark exchanged set | 005F0EF0 -> 0060D700 | Same extended layout, kind=33, set_id, operation=1 |
| Initial membership | 005E9C90 | 128 bytes at offset3959 including opcode, 32 set bytes at4087 |

`item`..`item9` category `卡片` has `動態資料1 = card_id` (e.g.
item5346 -> card1). The word Card in a name is not sufficient: EXP cards
and other consumables are separate systems.

`00668330` and `00667BE0` hide the reward panel for an already exchanged
set. The server independently rejects duplicate redemptions. The client
does not establish whether a historical official server consumed registered
membership on exchange. This implementation preserves membership and records
one redemption per set; this decision is explicit pending live evidence.

## Bugs corrected

- Card use previously consumed an item and printed a success message without
  recording its ID or updating the native UI.
- C2S0130 previously swapped inventory slots, although it is set exchange.
  Normal drag/drop continues on its existing opcode0012 path.
- C2S0132 from the Card/Furniture bag was not handled for registration.
- Initial membership and set flags came from the captured profile.
- No reward validation, capacity checks or persisted redemptions existed.

Registration and reward delivery are planned on a copy, then inventory and
Card Book are committed in one SQLite transaction to the exact character.
The existing backup/mirror notification runs after commit. Full inventory,
incomplete sets, invalid choices, duplicates and failed persistence leave
live items and membership unchanged. No live accounts are edited by the patch
or tests; previously consumed cards cannot be inferred/recovered automatically.

## Verification

`python -B tools/test_cardbook.py` runs isolated temporary-DB regressions:
real card mapping, unrelated EXP cards, single consumption from a stack,
duplicates, all/choice rewards, incomplete sets, full inventory with partial
capacity, failed save, wrong character, extended packets, actual0130/0132
routes, and the initial bitmaps using the real captured profile.

The existing `tools/test_character_card.py` has an unrelated baseline failure:
`test_bloque_cuenta_chars` expects HP max205 and receives0. This was reproduced
on the unchanged code before installing this patch; creation/login fields
outside the Card Book were not altered to address it.

Restart the server once, reconnect, use a genuine card in the Card bag and
verify it changes from grey to owned. Complete a set, exchange it, then
reconnect and verify both ownership and redemption remain. Client rendering
requires this in-game confirmation.

REA from the repository's main checkout was attempted, but its local Windows
native control module rejected `privateBridgeDescriptorAccess`; analysis
continued with the existing dump and direct PE instruction reads. REA/client
configuration was not modified.
