# The lexicon file: how it is created and maintained

Short version: the app creates a documented `lexicon.toml` on first use, you edit it (by hand or in
the dictionary window), and the app re-reads it whenever it changes. Nothing is downloaded or sent
anywhere at any point.

## 1. Creation

| When | What happens |
|---|---|
| The daemon starts (`parakeet-cage`) | `lexicon.toml` is created with a commented template, if it does not exist yet |
| You open the window (`parakeet-cage --dictionary`, or tray → *Dictionary…*) | the same check, so the file appears even if the daemon has never run |
| `[text] lexicon = false` in the config | no file is created and the dictionary stage is skipped entirely |

Paths — XDG-aware, so a sandbox or a different `$HOME` gets its own copy:

| File | Default location | Created |
|---|---|---|
| words | `~/.config/parakeet-cage/lexicon.toml` | on first use, from the template |
| candidates awaiting review | `~/.local/share/parakeet-cage/learning/pending.toml` | when a fuzzy match is first queued, or when you save from the window |

`[text] lexicon_path` overrides the words file; `[text] lexicon_max_distance` tunes fuzzy matching.

## 2. The life of an entry

1. **Notice a mishearing** — the model writes `Castrell` where you said `kestrel`.
2. **Add the word** — window: *Add word* → fill the word and its aliases → *Save*. Or edit the file
   directly in any editor.
3. **It applies from the next dictation** — the file is re-read whenever it changes, so there is no
   restart and no reload button.
4. **Corrections are counted** — the app rewrites only the `hits = N` values, in place. Comments,
   spacing and ordering you wrote are preserved.
5. **Wrong or obsolete?** Set `enabled = false`, delete the block, or press the tray's
   *Undo last correction* to re-paste a single utterance as the model heard it.

The other direction — the app tells you what is worth adding:

```bash
parakeet-cage --pending
```

lists near-misses it deliberately refused to apply (`heard "castle" → "kestrel"  (phonetic, distance
1, seen 3×)`). Accept one in the window (*Add as alias*) or copy the `heard` value into `aliases`
yourself.

## 3. Entry format

```toml
schema_version = 1

[[word]]
word = "kestrel"                  # what gets typed
aliases = ["castrell", "kestral"] # spellings the model produces instead
enabled = true                    # false switches just this entry off
hits = 0                          # maintained by the app
```

- `word` is required; the rest may be omitted.
- Matching is case-insensitive and whole-word only. Multi-word entries (`word = "Parakeet Cage"`)
  match as phrases.
- It is a plain text file: copy it, back it up, keep it in your dotfiles.

## 4. What the app will not do

- It cannot change what the model *hears* — the Parakeet TDT runtime rejects decoder hints — only
  what gets pasted.
- It only queues candidates that are near-misses of a word already in the file. Discovering
  brand-new vocabulary from your own transcripts is not implemented.
- It never rewrites a well-known word on a guess: a match must be exact, or — for rare words — share
  an identical consonant skeleton. Anything looser is queued in `pending.toml` instead.
