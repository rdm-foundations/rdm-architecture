#!/usr/bin/env python3
import yaml
import argparse
from pathlib import Path
from collections import defaultdict
import re


def load_glossary(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

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
        for letter in [chr(c) for c in range(ord('A'), ord('Z')+1)] + ["#"]:
            if letter not in groups:
                continue

            out.write(f"**{letter}**\n\n")
            out.write("| Term | Definition |\n")
            out.write("|------|------------|\n")

            for term in groups[letter]:
                definition = glossary[term].get("def", "").replace("\n", " ").strip()
                
                # Create a clean, url-friendly ID (lowercased, spaces to dashes, removes special chars)
                gidx = term.lower().strip()
                gidx = re.sub(r'[^a-z0-9\s-]', '', gidx)
                gidx = re.sub(r'[\s-]+', '-', gidx)
                
                # Injected the <span id="..."> tag right before the term name
                out.write(f"| <span id=\"{gidx}\"></span>{term} | {definition} |\n")

            out.write("\n")

def main():
    parser = argparse.ArgumentParser(
        description="Generate a full, alphabetically sorted glossary.qmd from glossary.yml"
    )
    parser.add_argument("-i", "--input", required=True, help="Input YAML file")
    parser.add_argument("-o", "--output", required=True, help="Output QMD file")

    args = parser.parse_args()

    glossary = load_glossary(args.input)
    write_qmd(glossary, args.output)

    print(f"Glossary written to {args.output}")

if __name__ == "__main__":
    main()
