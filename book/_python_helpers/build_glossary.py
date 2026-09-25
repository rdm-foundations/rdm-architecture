#!/usr/bin/env python3
"""
1. Reads glossary terms from a YAML file and writes an alphabetically
   grouped glossary.qmd, with each term wrapped in
   <span id="..."></span> so it can be linked to.
2. Scans all other .qmd files in a directory and turns plain-text mentions
   of those terms into links, e.g.:

       RDM Life Cycle  ->  [RDM Life Cycle](glossary.qmd#rdm-life-cycle)

How the linking avoids the tricky cases
----------------------------------------
* Longer terms are matched before shorter ones, so "RDM Life Cycle" is
  consumed whole and the standalone "RDM" pattern never gets a chance to
  match the "RDM" sitting inside it.
* Matches require non-word/non-hyphen boundaries on both sides, so "RDM"
  will NOT match inside "RDMS", "pre-RDM", "RDM-based" etc.
* Fenced code blocks, inline code spans, YAML frontmatter, existing
  markdown links, and headings are masked out before matching (and
  restored afterwards).
* By default only the FIRST occurrence of each term per file is turned
  into a link (typical glossary convention) -- pass --link-all to link
  every occurrence instead.
* The glossary output file itself is skipped when scanning for terms to
  link, so it doesn't link to itself.

Usage
-----
    python build_glossary.py -i glossary_terms.yml -o glossary.qmd \
        --docs-dir . --link-terms

    # preview without writing changes to the other .qmd files:
    python build_glossary.py -i glossary_terms.yml -o glossary.qmd \
        --docs-dir . --link-terms --dry-run
"""

import argparse
import re
from collections import defaultdict
from pathlib import Path

import yaml

LINK_ALL_OCCURRENCES_DEFAULT = False  # only first mention per file gets linked
FILE_GLOB = "*.qmd"


def load_glossary(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def slugify(term):
    """Same scheme used for the <span id="..."> anchors, kept as a single
    shared function so the glossary anchors and the generated links always
    agree with each other."""
    gidx = term.lower().strip()
    gidx = re.sub(r'[^a-z0-9\s-]', '', gidx)
    gidx = re.sub(r'[\s-]+', '-', gidx)
    return gidx


def write_qmd(glossary, output_path):
    # Sort terms alphabetically
    terms = sorted(glossary.keys())

    # Group terms by first letter
    groups = defaultdict(list)
    for term in terms:
        first_letter = term[0].upper()
        if not first_letter.isalpha():
            first_letter = "#"  # non‑alphabetic bucket
        groups[first_letter].append(term)

    with open(output_path, "w") as out:
        out.write("# Glossary\n\n")

        # Iterate A–Z plus "#" bucket
        for letter in [chr(c) for c in range(ord('A'), ord('Z') + 1)] + ["#"]:
            if letter not in groups:
                continue

            out.write(f"**{letter}**\n\n")
            out.write("| Term | Definition |\n")
            out.write("|------|------------|\n")

            for term in groups[letter]:
                definition = glossary[term].get("def", "").replace("\n", " ").strip()
                gidx = slugify(term)
                out.write(f"| <span id=\"{gidx}\"></span>{term} | {definition} |\n")

            out.write("\n")


# Region protection: mask out spans we must not touch, restore afterwards
PROTECT_PATTERNS = [
    re.compile(r"^---\n.*?\n---\n", re.DOTALL),          # YAML frontmatter
    re.compile(r"```.*?```", re.DOTALL),                  # fenced code blocks
    re.compile(r"`[^`\n]+`"),                              # inline code
    re.compile(r"\[[^\]]*\]\([^)]*\)"),                    # existing md links
    re.compile(r"^#{1,6}[ \t].*$", re.MULTILINE),          # headings
]

PLACEHOLDER = "\x00{}\x00"


def mask_protected_regions(text):
    stash = []

    def _stash(match):
        stash.append(match.group(0))
        return PLACEHOLDER.format(len(stash) - 1)

    for pattern in PROTECT_PATTERNS:
        text = pattern.sub(_stash, text)
    return text, stash


def unmask_protected_regions(text, stash):
    for i, original in enumerate(stash):
        text = text.replace(PLACEHOLDER.format(i), original)
    return text


def build_term_regex(terms):
    """terms: dict {term: slug}"""
    # Longest term first so multi-word terms are matched before their
    # shorter substrings (e.g. "RDM Life Cycle" before "RDM").
    ordered = sorted(terms.keys(), key=len, reverse=True)
    escaped = [re.escape(t) for t in ordered]
    alternation = "|".join(escaped)
    # Boundaries: not preceded/followed by a word char or hyphen, so we
    # don't match inside larger words or hyphenated compounds.
    pattern = rf"(?<![\w-])(?:{alternation})(?![\w-])"
    return re.compile(pattern, re.IGNORECASE)


def link_terms_in_text(text, terms, term_regex, glossary_file, link_all):
    """Return (new_text, number_of_links_added)."""
    protected_text, stash = mask_protected_regions(text)

    # case-insensitive lookup: matched text -> canonical term key
    lower_lookup = {t.lower(): t for t in terms}

    already_linked = set()
    count = 0

    def _replace(match):
        nonlocal count
        matched_text = match.group(0)
        canonical = lower_lookup[matched_text.lower()]

        if not link_all and canonical in already_linked:
            return matched_text

        already_linked.add(canonical)
        count += 1
        slug = terms[canonical]
        return f"[{matched_text}]({glossary_file}#{slug})"

    new_protected_text = term_regex.sub(_replace, protected_text)
    new_text = unmask_protected_regions(new_protected_text, stash)
    return new_text, count


def link_terms_in_files(glossary, docs_dir, glossary_file, link_all, dry_run, single_file=None):
    terms = {term: slugify(term) for term in glossary.keys()}
    term_regex = build_term_regex(terms)

    glossary_basename = Path(glossary_file).name

    if single_file is not None:
        qmd_files = [Path(single_file)]
        if qmd_files[0].name == glossary_basename:
            print(f"Skipping {qmd_files[0]}: it is the glossary file itself.")
            return
        if not qmd_files[0].exists():
            print(f"File not found: {qmd_files[0]}")
            return
    else:
        docs_dir = Path(docs_dir)
        qmd_files = sorted(docs_dir.rglob(FILE_GLOB))
        qmd_files = [f for f in qmd_files if f.name != glossary_basename]

        if not qmd_files:
            print(f"No {FILE_GLOB} files found under {docs_dir} (besides the glossary itself).")
            return

    total_links = 0
    for path in qmd_files:
        original = path.read_text(encoding="utf-8")
        new_text, n = link_terms_in_text(
            original, terms, term_regex, glossary_basename, link_all
        )

        if n == 0:
            continue

        total_links += n
        status = "[dry-run]" if dry_run else "[updated]"
        print(f"{status} {path}: {n} term(s) linked")

        if not dry_run:
            path.write_text(new_text, encoding="utf-8")

    print(f"\nLinking done. {total_links} link(s) "
          f"{'would be ' if dry_run else ''}added across {len(qmd_files)} file(s) scanned.")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a full, alphabetically sorted glossary.qmd from glossary.yml, "
        "and optionally auto-link mentions of those terms across other .qmd files."
    )
    parser.add_argument("-i", "--input", required=True, help="Input YAML file")
    parser.add_argument("-o", "--output", required=True, help="Output QMD file")
    parser.add_argument(
        "--link-terms",
        action="store_true",
        help="Also scan --docs-dir for .qmd files and turn mentions of glossary "
        "terms into links pointing at the generated glossary file.",
    )
    parser.add_argument(
        "--docs-dir",
        default=".",
        help="Directory to search for .qmd files when --link-terms is used "
        "(recursive). Default: current dir. Ignored if --file is given.",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="With --link-terms: link terms in just this one .qmd file, "
        "instead of scanning --docs-dir.",
    )
    parser.add_argument(
        "--link-all",
        action="store_true",
        help="Link every occurrence of a term, not just the first one per file "
        "(only relevant with --link-terms).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --link-terms: show what would change without writing files.",
    )

    args = parser.parse_args()

    glossary = load_glossary(args.input)
    write_qmd(glossary, args.output)
    print(f"Glossary written to {args.output}")

    if args.link_terms:
        link_terms_in_files(
            glossary,
            docs_dir=args.docs_dir,
            glossary_file=args.output,
            link_all=args.link_all,
            dry_run=args.dry_run,
            single_file=args.file,
        )


if __name__ == "__main__":
    main()
