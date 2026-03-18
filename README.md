# ibtool reimplementation

This project reimplements the behaviour of Apple's `actool`. It's a clean
reimplementation based just on the behaviour and the awesome research from
[Alexandre Colucci](https://blog.timac.org/2018/1018-reverse-engineering-the-car-file-format/)
who described the file structure.

This tool supports the lzfse compression for assets, but not the palette and
deepmap proprietary formats.

There is likely some missing functionality, in the unknown unknowns category.
As more samples appear or issues get reported, better compatibility will be
achieved.

The target at this point is just macos behaviour and iOS-specific features may
be missing. (please report those)

## Implementation

The system has been implemented almost entirely automatically by Claude with
deciduous planning.
