#!/usr/bin/env python3

import argparse
import pandas as pd
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Convert .dta file to .csv using pandas")
    parser.add_argument("--input", required=True, help="Path to input .dta file")
    parser.add_argument("--output", required=False, help="Path to output .csv file")
    parser.add_argument("--chunksize", type=int, default=None,
                        help="Optional chunk size for large files (e.g., 100000)")
    parser.add_argument("--compress", action="store_true",
                        help="Write output as gzip-compressed CSV (.csv.gz)")
    args = parser.parse_args()

    input_path = Path(args.input)

    if args.output:
        output_path = Path(args.output)
    else:
        suffix = ".csv.gz" if args.compress else ".csv"
        output_path = input_path.with_suffix(suffix)

    if args.chunksize:
        # Chunked read/write for very large files
        reader = pd.read_stata(input_path, chunksize=args.chunksize)
        first = True
        for chunk in reader:
            chunk.to_csv(
                output_path,
                mode="w" if first else "a",
                index=False,
                header=first,
                compression="gzip" if args.compress else None
            )
            first = False
    else:
        df = pd.read_stata(input_path)
        df.to_csv(
            output_path,
            index=False,
            compression="gzip" if args.compress else None
        )

    print(f"Wrote: {output_path}")

if __name__ == "__main__":
    main()
