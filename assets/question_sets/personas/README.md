# Persona descriptions for the polarization and depolarization sets

The question sets in `../polarization/` and `../depolarization/` were searched and validated
with one pair of starting personas (GSS 2024): the facts of the configured `gss2024_cm` /
`gss2024_wf` presets **plus** party, religion, religious attendance, marital status and
education. The extra attributes matter. Without them, the model gives the two personas nearly
identical answers on opinion items, and neither set works.

These descriptions are written so that, read correctly, they decode to exactly that starting
state (`target_states.json`). Use them as the respondent description (*Who*) instead of the
short preset texts.

| File | Persona |
|---|---|
| `gss2024_cm_rich.txt` | conservative, rural Alabama man (CM) |
| `gss2024_wf_rich.txt` | progressive New York City woman (WF) |
| `target_states.json` | the 15 GSS 2024 assignments each description should produce |

## Phrase → survey assignment

| Variable | CM phrase → label | WF phrase → label |
|---|---|---|
| `sex`, `age`, `race` | man, 45, white → `male`, `45`, `white` | woman, 22, white → `female`, `22`, `white` |
| `region` | Alabama, in the South → `south` | New York, the Northeast → `northeast` |
| `xnorcsiz` | open country → `open country within larger civil divisions …` | New York City, a large central city → `a large central city (over 250,000)` |
| `marital`, `childs` | married, two children → `married`, `2` | never married, no children → `never married`, `0` |
| `wrkstat` | works full time → `working full time` | works full time → `working full time` |
| `vetyears` | 2 to 4 years of active duty → `yes, 2-4 years` | never served → `no active duty` |
| `news` | reads a newspaper every day → `every day` | same → `every day` |
| `degree` | high school diploma, no college → `high school` | bachelor's degree → `bachelor's` |
| `polviews` | conservative → `conservative` | extremely liberal → `extremely liberal` |
| `partyid` | strong Republican → `strong republican` | strong Democrat → `strong democrat` |
| `relig`, `attend` | Protestant, every week → `protestant`, `every week` | no religion, never → `none`, `never` |

Wording choices that keep the decoding clean:
- **Close to the GSS answer labels.** For example, "thinks of himself as conservative", not "highly conservative". CM is deliberately `conservative`, not `extremely conservative`.
- **One mention per fact**, and no extra traits that could become other survey variables.
- **"Reads a newspaper every day"** matches the GSS `news` item; "regular news consumer" does not.
- **Place type rather than a population number**, because the size variable is coded by type.

## Check the decoding

In the web app, start the respondent and open *Initial state (persona + forced assignments)*
in the right panel. All 15 variables should be present with the labels above. Party, religion
and attendance are the ones that separate the two personas; if any of those is missing or
different, the run is not under the validated conditions. The validation also allowed for
variation around this state (age, place size, strength of views, an omitted fact), so small
differences elsewhere are within what was tested.

Details of the analysis: [`QUESTION_OPTIMIZATION.md`](../../../QUESTION_OPTIMIZATION.md).
