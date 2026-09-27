# Reaction GIFs for the reveal

Drop GIFs (or .webp / .png) here, then `npm run build`. The file name decides when one plays:

| File name starts with | Plays when |
| --- | --- |
| `67-` | a 67 is on screen: the claim, the composure or the score is 67 (wins over everything else) |
| `validated-` | gap 10 or less (the narrator's "validated" tier) |
| `mild-` | gap 11-25 |
| `spicy-` | gap 26-45 |
| `delulu-` | gap over 45 |
| `any-` | any result, when nothing more specific is here |

Several files with the same prefix: one is picked per round (the same one for that round every time).
No matching file: no GIF, the reveal is unchanged. Examples: `67-six-seven.gif`, `validated-scuba.gif`,
`delulu-freaky-hamster.gif`.

These files are not committed (see `.gitignore`): memes and film clips belong to their owners.
Keep each under a few MB; they load from the booth machine, no network needed.
