# Summary — chapter_19_bibliography

- 19-000…19-003 (batch 1): heading «# Библиография»; alphabetical entries Adams → Department of Energy (45 entries). Convention set for the whole chapter: citation cores stay EN verbatim (style guide §6), only apparatus russified — «[accessed D Month YYYY]» → «[дата обращения: D месяца YYYY г.]»; no other translation. Entry paragraphs separated by blank lines, as in EN.
- Gate note: sentence-count check structurally false-positives on bibliography chunks (entries lack terminal punctuation; RU abbrev «г.» merges splits). Verify instead by paragraph count + core-identity diff; char ratio ~1.03.
- 19-004…19-007 (batch 2): entries Derrida → Library of Congress (46 entries). Same convention: EN cores verbatim, only «[accessed …]» → «[дата обращения: …]»; two Hudson/Kobrin-style entries and Levi & Reuter have no accessed-date — left untouched. Roundtrip diff (reverse the apparatus substitution) reproduces EN exactly; paragraph counts match (11/12/11/12).
- Gate again false-positives on sentence delta (known structural issue for this chapter); verified by paragraph count + byte-identical roundtrip instead. Char ratios 1.02–1.04.
