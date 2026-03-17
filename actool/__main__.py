"""
actool - Asset Catalog Tool

CLI-compatible reimplementation of Apple's actool for compiling xcassets.
"""

import argparse
import sys

from .compiler import compile_catalog


def main():
    parser = argparse.ArgumentParser(
        description="Compile asset catalogs (.xcassets)")

    parser.add_argument("input", help="Path to .xcassets directory")
    parser.add_argument("--compile", metavar="DIR",
                        help="Output directory for compiled assets")
    parser.add_argument("--platform", default="macosx",
                        help="Target platform (default: macosx)")
    parser.add_argument("--minimum-deployment-target", default="11.0",
                        help="Minimum deployment target version")
    parser.add_argument("--app-icon", metavar="NAME",
                        help="Name of the app icon set to compile")
    parser.add_argument("--output-partial-info-plist", metavar="PATH",
                        help="Path for the output partial info plist")

    args = parser.parse_args()

    if not args.compile:
        parser.error("--compile is required")

    compile_catalog(
        xcassets_path=args.input,
        output_dir=args.compile,
        platform=args.platform,
        min_deploy=args.minimum_deployment_target,
        app_icon=args.app_icon,
        info_plist_path=args.output_partial_info_plist,
    )


if __name__ == "__main__":
    main()
